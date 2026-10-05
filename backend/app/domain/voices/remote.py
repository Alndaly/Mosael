"""克隆音色在远端的副本(ADR 0037):一把嗓子,本机和远端两种念法。

一把嗓子仍是一行 `Voice`(参考音频 + 文字 + 授权声明)。用 CosyVoice 念它时,宿主在合成前把它解析成「这个人的连接 +
当前 CosyVoice 模型」下的一份**副本**(`VoiceEnrollment`):有 `ok` 的就用;没有就把参考音频传上去、`create_voice`、
等它就绪。配音、字幕逐句配音、AI 工作台、智能体语音对话、工作流的配音节点都走 `voices.speak_to_file`,解析放在那一处,
入口不用各自认识复刻。

几条规矩:

- **上传要点头,而且只点一次**。参考音频离开这台机器、进到第三方账号里,第一次用到时要当事人确认(`RemoteConsentRequired`
  —— 接口回 409 带 `code`,界面弹一个说清楚去哪、存多久、删嗓子会不会一起删的确认框)。同意记在副本上;同一把嗓子、同一个
  引擎、同一个账号里有过一份副本就算点过,之后换模型、副本被删按需重建,不再问。
- **没声明授权的嗓子不复刻**(`consent_kind == undeclared`,和数字人同一条线):不知道是谁的嗓子,不往外传。
- **本机的参考音频是唯一的来源**。副本丢了(一年没被合成用过会被远端删掉)随时重建:合成失败时按前缀列一遍,它不在了就
  标 `missing`、重建一次再念,再失败才报错。
- **删嗓子先删远端**:逐个 `delete_voice`,删不掉的(钥匙失效、网络)列出来告诉用户,本机这行照删。

状态一律在**自己的短事务**里写(`unit_of_work`),不借调用方的会话:副本建好了就是建好了,不随这一次合成的成败回滚;
而复刻要十来秒,不能占着调用方的写锁。
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.core.unit_of_work import unit_of_work
from app.db.model_base import now
from app.db.models import Job, ProviderProfile, Voice, VoiceEnrollment
from app.domain.voices.consent import UNDECLARED
from app.domain.voices.errors import VoiceError
from app.domain.voices.speech import BUILTIN_PREFIX, adapter_id
from app.domain.voices.target import speech_target
from app.media.paths import resolve_key

logger = logging.getLogger(__name__)

#: 副本的四种状态。
DEPLOYING = "deploying"
OK = "ok"
FAILED = "failed"
#: 远端说没有这个音色了(一年没被合成用过被删、钥匙换了账号)。下一次用到时重建。
MISSING = "missing"

#: 建好之后等它就绪的上限。实测约 10 秒从 DEPLOYING 到 OK。
ENROLL_TIMEOUT_SECONDS = 120.0
POLL_SECONDS = 2.0

#: 「这个账号还没同意上传这把嗓子」的那个 409 的 `code`。界面认它弹确认框。
CONSENT_REQUIRED = "remote_voice_consent_required"


class RemoteConsentRequired(LocalizedError, RuntimeError):
    """要把参考音频传到第三方账号里,而这个账号还没同意过。**不是故障**:界面据此弹确认框,同意后再来一次。

    不是 VoiceError:各条路由把 VoiceError 翻成 422 + 一句话,而这一个要带着结构(哪把嗓子、哪条连接、哪个模型)
    回 409,让界面说得清「传到哪」。翻译在 main.py 的异常处理里,一处。
    """

    def __init__(self, voice: Voice, *, engine: str, provider_profile_id: str, connection: str, model: str) -> None:
        super().__init__("voiceErr_remoteConsentRequired", voice=voice.name, connection=connection, model=model)
        self.voice_id = voice.id
        self.engine = engine
        self.provider_profile_id = provider_profile_id

    def detail(self) -> dict[str, Any]:
        return {
            "code": CONSENT_REQUIRED,
            "message": str(self),
            "voice_id": self.voice_id,
            "voice_name": self.params["voice"],
            #: 能力表里的引擎 id(`builtin:alibaba-cosyvoice`),界面拿它回来调复刻接口。
            "engine": f"{BUILTIN_PREFIX}{self.engine}",
            "provider_profile_id": self.provider_profile_id,
            "connection": self.params["connection"],
            "model": self.params["model"],
        }


def clones_remotely(engine: str) -> bool:
    """这个配音引擎能不能念配音库里的克隆音色(把嗓子复刻上去)。收能力表 id(`builtin:…`)或裸名。"""
    from app.ai.providers import VOICE_ENROLLMENT_ADAPTERS

    return bool(engine) and adapter_id(engine) in VOICE_ENROLLMENT_ADAPTERS


def prefix_for(voice_id: str) -> str:
    """远端音色名里的前缀:`m` + 嗓子 id 的前 9 位(十个字符以内、只有字母数字)。

    按前缀 `list_voice` 时认得出哪条是 Mosael 建的、对应哪把嗓子 —— 删嗓子时连没登记上的(建到一半进程没了)也一起清掉。
    """
    return f"m{voice_id[:9]}"


@dataclass(frozen=True)
class Account:
    """副本在谁的账号里:引擎(裸名)、连接、钥匙的主人,和这次用的那把钥匙(不落库)。"""

    engine: str
    provider_profile_id: str
    owner_user_id: str
    connection: str
    api_key: str
    base_url: str

    @classmethod
    def of(cls, engine: str, profile: Any, user_id: str) -> Account:
        return cls(
            engine=adapter_id(engine),
            provider_profile_id=profile.id,
            owner_user_id=user_id,
            connection=profile.name,
            api_key=profile.api_key or "",
            base_url=profile.base_url or "",
        )

    def adapter(self):
        from app.ai.providers import build_voice_enrollment_adapter

        return build_voice_enrollment_adapter(self.engine, api_key=self.api_key, base_url=self.base_url)


@dataclass(frozen=True)
class Copy:
    """解析出来的一份副本:它那一行的 id,和远端的音色 id(交给语音适配器当 `voice`)。"""

    id: str
    remote_voice_id: str


# ---------------- 判据 ----------------


def refuse_undeclared(voice: Voice) -> None:
    """没声明是谁的嗓子,不往外传(ADR 0028 §5 的同一条线)。"""
    if voice.consent_kind == UNDECLARED:
        raise VoiceError("voiceErr_remoteCloneUndeclared", voice=voice.name)


def _same_account(query, voice_id: str, account: Account):
    return query.where(
        VoiceEnrollment.voice_id == voice_id,
        VoiceEnrollment.engine == account.engine,
        VoiceEnrollment.provider_profile_id == account.provider_profile_id,
        VoiceEnrollment.owner_user_id == account.owner_user_id,
    )


def _consented(db: Session, voice_id: str, account: Account) -> VoiceEnrollment | None:
    """这个账号里这把嗓子的任意一份副本 —— 有一份就说明同意过上传(同意记在副本上)。"""
    return db.scalars(_same_account(select(VoiceEnrollment), voice_id, account).order_by(VoiceEnrollment.created_at)).first()


def require_consent(db: Session, voice: Voice, account: Account, *, model: str) -> None:
    """这个账号同意过把这把嗓子传上去没有。没同意就快速失败(建任务之前),带着界面要说的那几样。"""
    if _consented(db, voice.id, account) is None:
        raise RemoteConsentRequired(
            voice, engine=account.engine, provider_profile_id=account.provider_profile_id,
            connection=account.connection, model=model,
        )


def check_voice(
    db: Session,
    *,
    engine: str,
    voice_id: str,
    workspace_id: str,
    user_id: str | None,
    provider_profile_id: str | None = None,
    engine_model: str = "",
) -> Voice:
    """用远端引擎念配音库里的一把嗓子之前,**建任务之前**问清楚:嗓子在这个工作区、声明过是谁的、这个账号同意过上传。

    没配连接时不在这里说 —— 合成那一步会说缺钥匙,那句话指得到设置页。
    """
    voice = db.get(Voice, voice_id)
    if voice is None or (workspace_id and voice.workspace_id != workspace_id):
        raise VoiceError("voiceErr_voiceNotInWorkspace")
    refuse_undeclared(voice)
    profile, model = speech_target(
        db, engine, user_id=user_id, provider_profile_id=provider_profile_id, model_override=engine_model
    )
    if profile is not None and user_id:
        require_consent(db, voice, Account.of(engine, profile, user_id), model=model)
    return voice


def speaks_library_voice(db: Session, engine: str, voice: str) -> bool:
    """「引擎 + 一格音色」里那一格是不是配音库里的嗓子、交给能复刻的远端引擎念(智能体的卡只有一格音色)。
    嗓子 id 是 32 位 hex,和引擎自己的音色名(`longxiaochun_v2`)撞不上。"""
    return bool(voice) and clones_remotely(engine) and db.get(Voice, voice) is not None


# ---------------- 同意 + 复刻任务(配音库的「复刻到百炼」、确认框点了同意) ----------------


def start_enrollment(
    db: Session,
    voice: Voice,
    *,
    engine: str,
    actor_id: str,
    consent: bool,
    provider_profile_id: str | None = None,
) -> Job:
    """排一个复刻任务;`consent` 为真时先记下这个账号同意上传这把嗓子。

    这个账号还没同意过、这一次也没带同意 → `RemoteConsentRequired`(和合成那边同一个 409,界面弹同一个确认框,
    同意了再带着 `consent` 来一次)。同意过的(重新复刻失败了的、被百炼删了的)不再问。

    同意落在这个账号、当前模型那一份副本上(还没有就建一行 `deploying`)。任务里建远端音色、等它就绪;合成那边如果
    同时也要用它,会在同一把锁上等这一份,不会建出第二个。
    """
    from app.domain.jobs import create_job, dispatch_job

    if not clones_remotely(engine):
        raise VoiceError("voiceErr_remoteCloneUnsupported", engine=engine)
    refuse_undeclared(voice)
    profile, model = speech_target(db, engine, user_id=actor_id, provider_profile_id=provider_profile_id)
    if profile is None:
        raise VoiceError("voiceErr_remoteNoConnection")
    account = Account.of(engine, profile, actor_id)
    earlier = _consented(db, voice.id, account)
    if earlier is None and not consent:
        raise RemoteConsentRequired(
            voice, engine=account.engine, provider_profile_id=account.provider_profile_id,
            connection=account.connection, model=model,
        )
    row = _row(db, voice.id, account, model)
    if row is None:
        row = VoiceEnrollment(
            voice_id=voice.id,
            engine=account.engine,
            provider_profile_id=account.provider_profile_id,
            owner_user_id=account.owner_user_id,
            target_model=model,
            status=DEPLOYING,
            consented_by=earlier.consented_by if earlier is not None else actor_id,
            consented_at=earlier.consented_at if earlier is not None else now(),
        )
        db.add(row)
        db.flush()
    job = create_job(
        db,
        workspace_id=voice.workspace_id,
        kind="voice_enroll",
        created_by=actor_id,
        payload={
            "subject": voice.name,
            "voice_id": voice.id,
            "engine": f"{BUILTIN_PREFIX}{account.engine}",
            "provider_profile_id": account.provider_profile_id,
            "target_model": model,
        },
        message="jobMsg_remoteVoiceQueued",
        message_params={"voice": voice.name},
    )
    job_id = job.id
    dispatch_job(db, job, lambda: _run_enrollment(job_id))
    return job


def _run_enrollment(job_id: str) -> None:
    from app.domain.jobs import run_job_guarded

    run_job_guarded(job_id, lambda: _enrollment_body(job_id), what="复刻音色")


def _enrollment_body(job_id: str) -> None:
    from app.domain.jobs import blame, emit_job_event, finish_job, say

    with unit_of_work() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        payload = dict(job.payload or {})
        voice_id, engine = str(payload.get("voice_id") or ""), str(payload.get("engine") or "")
        actor = job.created_by or ""
        voice = db.get(Voice, voice_id)
        if voice is None:
            raise VoiceError("voiceErr_voiceNotFound")
        if not finish_job(db, job, status="running", progress=0.1):
            return
        say(job, "jobMsg_remoteVoiceEnrolling", voice=voice.name)
        emit_job_event(db, job.id, "job.running", {})
        profile, resolved = speech_target(
            db, engine, user_id=actor, provider_profile_id=str(payload.get("provider_profile_id") or "") or None,
        )
        if profile is None:
            raise VoiceError("voiceErr_remoteNoConnection")
        #: 建在排任务那一刻定下的模型上(同意就落在那一份副本上),中途有人改了连接的模型也不漂。
        model = str(payload.get("target_model") or "") or resolved
        account = Account.of(engine, profile, actor)
        voice_name = voice.name
        existing = _row(db, voice_id, account, model)
        standing = Copy(existing.id, existing.remote_voice_id) if existing is not None and existing.status == OK else None
    try:
        #: 有人亲手点了「复刻到百炼」而这一份看上去好好的:问一句远端它还在不在(一年没用会被删),不在就重建 ——
        #: 不然这一下什么都不做,要等到下次配音失败才知道。
        if standing is not None and vanished(voice_id, account, standing):
            mark_missing(standing)
        copy = ensure_copy(voice_id, account, model=model)
    except Exception as exc:  # noqa: BLE001 —— 失败是这个任务的结果(远端的原话),不是工作线程崩了
        with unit_of_work() as db:
            job = db.get(Job, job_id)
            if job is not None and finish_job(db, job, status="failed", **blame(exc)):
                say(job, "jobMsg_remoteVoiceFailed", voice=voice_name)
                emit_job_event(db, job.id, "job.failed", {})
        logger.warning("复刻音色 %s 失败:%s", voice_id, str(exc)[:300])
        return
    with unit_of_work() as db:
        job = db.get(Job, job_id)
        result = {"voice_id": voice_id, "enrollment_id": copy.id, "target_model": model}
        if job is not None and finish_job(db, job, status="succeeded", progress=1.0, result=result):
            say(job, "jobMsg_remoteVoiceDone", voice=voice_name, model=model)
            emit_job_event(db, job.id, "job.succeeded", dict(result))


# ---------------- 解析副本(合成前)与重建 ----------------

_locks_guard = threading.Lock()
#: (嗓子, 引擎, 连接, 钥匙主人, 模型) → 那一份副本的锁。同一份副本同一时刻只有一个线程在建:复刻任务和一次配音同时
#: 要它时,后到的等先到的建完直接用 —— 否则账号里会多出一个没人认领的音色。见 docs/PROCESS_STATE.md。
_copy_locks: dict[tuple[str, ...], threading.Lock] = {}


@contextmanager
def _copy_lock(key: tuple[str, ...]) -> Iterator[None]:
    with _locks_guard:
        lock = _copy_locks.setdefault(key, threading.Lock())
    with lock:
        yield


def _row(db: Session, voice_id: str, account: Account, model: str) -> VoiceEnrollment | None:
    return db.scalars(
        _same_account(select(VoiceEnrollment), voice_id, account).where(VoiceEnrollment.target_model == model)
    ).first()


def ensure_copy(
    voice_id: str,
    account: Account,
    *,
    model: str,
    on_enroll: Callable[[str], None] | None = None,
) -> Copy:
    """这把嗓子在这个账号、这个模型上那一份**就绪的**副本:有 `ok` 的就用;没有就上传、建、等到就绪。

    要同意过(这个账号里有过任意一份副本);没同意过抛 `RemoteConsentRequired`。`on_enroll(嗓子名)` 在真要去建的那一刻
    调一次(配音任务据此把进度写成「正在百炼上复刻这把嗓子」)。
    """
    with _copy_lock((voice_id, account.engine, account.provider_profile_id, account.owner_user_id, model)):
        with unit_of_work() as db:
            voice = db.get(Voice, voice_id)
            if voice is None:
                raise VoiceError("voiceErr_voiceNotFound")
            refuse_undeclared(voice)
            row = _row(db, voice_id, account, model)
            if row is not None and row.status == OK and row.remote_voice_id:
                return Copy(row.id, row.remote_voice_id)
            if row is None:
                # 换了模型:这个账号同意过就照建,不再问。
                consent = _consented(db, voice_id, account)
                if consent is None:
                    raise RemoteConsentRequired(
                        voice, engine=account.engine, provider_profile_id=account.provider_profile_id,
                        connection=account.connection, model=model,
                    )
                row = VoiceEnrollment(
                    voice_id=voice_id,
                    engine=account.engine,
                    provider_profile_id=account.provider_profile_id,
                    owner_user_id=account.owner_user_id,
                    target_model=model,
                    consented_by=consent.consented_by,
                    consented_at=consent.consented_at,
                )
                db.add(row)
            #: 上一次建了、还没等到就绪(超时、进程重启):接着等那一个,不再建一个新的。
            pending = row.remote_voice_id if row.status == DEPLOYING else ""
            row.status = DEPLOYING
            row.error = ""
            row.remote_voice_id = pending
            db.flush()
            row_id, voice_name, workspace_id = row.id, voice.name, voice.workspace_id
            reference = resolve_key(voice.reference_key)
        if not reference.is_file():
            _settle(row_id, FAILED, error="voiceErr_referenceMissing")
            raise VoiceError("voiceErr_referenceMissing")
        if on_enroll is not None:
            on_enroll(voice_name)
        remote_id = pending
        try:
            adapter = account.adapter()
            if not remote_id:
                remote_id = _create(adapter, account, voice_id=voice_id, workspace_id=workspace_id, model=model,
                                    reference=reference)
                with unit_of_work() as db:
                    db.get(VoiceEnrollment, row_id).remote_voice_id = remote_id
            _wait_until_ready(adapter, remote_id)
        except _StillDeploying:
            # 远端还在建:留着 deploying 和它的 id,下一次用到时接着等这一个。
            raise VoiceError("voiceErr_remoteEnrollTimeout", voice=voice_name) from None
        except Exception as exc:
            _settle(row_id, FAILED, error=str(exc)[:1000])
            raise
        _settle(row_id, OK)
        return Copy(row_id, remote_id)


def _create(adapter, account: Account, *, voice_id: str, workspace_id: str, model: str, reference) -> str:
    """传参考音频、建音色。记一条用量(`tts` / `enroll_voice`,免费):账上看得到哪天、哪把嗓子、传到了哪条连接。"""
    from app.ai.providers import connection_vendor_for_speech_engine
    from app.domain.billing.usage import billable, once

    with unit_of_work() as db, billable(
        db,
        capability="tts",
        operation="enroll_voice",
        idempotency_key=once("enroll_voice"),
        workspace_id=workspace_id,
        provider=connection_vendor_for_speech_engine(account.engine),  # 和合成同一个口径,见 voices.speak_to_file
        model=model,
        provider_profile_id=account.provider_profile_id,
        source_type="voice",
        source_id=voice_id,
    ) as call:
        call.meter(requests=1)
        call.mark_free()
        return adapter.create(target_model=model, prefix=prefix_for(voice_id), reference=reference)


class _StillDeploying(Exception):
    """等到上限还没就绪。"""


def _wait_until_ready(adapter, remote_id: str) -> None:
    from app.ai.providers.contracts.voice_enrollment import READY, REJECTED

    deadline = time.monotonic() + ENROLL_TIMEOUT_SECONDS
    while True:
        found = adapter.query(remote_id)
        if found.status == READY:
            return
        if found.status == REJECTED:
            # 没通过(百炼说 UNDEPLOYED):那个音色留着没用,顺手删掉;删不掉不影响这一次的结论。
            try:
                adapter.delete(remote_id)
            except Exception:  # noqa: BLE001
                logger.info("删不掉没通过的远端音色 %s", remote_id, exc_info=True)
            raise VoiceError("voiceErr_remoteEnrollRejected", status=found.raw_status or "?")
        if time.monotonic() >= deadline:
            raise _StillDeploying()
        time.sleep(POLL_SECONDS)


def _settle(row_id: str, status: str, *, error: str = "") -> None:
    with unit_of_work() as db:
        row = db.get(VoiceEnrollment, row_id)
        if row is not None:
            row.status = status
            row.error = error


def vanished(voice_id: str, account: Account, copy: Copy) -> bool:
    """合成失败之后问一句:这份副本还在不在远端。按前缀列一遍,不在列表里就是没了。

    不靠认合成报错的原话:真机(2026-10-05)上被删的音色再拿去念,百炼回的是
    `InvalidParameter: [cosyvoice]Engine return error code: 418` —— 和把 v2 的音色发给 v3 是同一句,分不出是哪一种;
    而「列表里有没有它」是确定的。问不到(网络)就当它还在 —— 这次的失败照原样报,不去重建一个可能还好好的副本。
    """
    try:
        listed = account.adapter().list(prefix=prefix_for(voice_id))
    except Exception:  # noqa: BLE001
        logger.info("问不到远端音色列表,不判它没了", exc_info=True)
        return False
    return copy.remote_voice_id not in {one.voice_id for one in listed}


def mark_missing(copy: Copy) -> None:
    _settle(copy.id, MISSING, error="voiceErr_remoteCopyMissing")


def touch(copy: Copy) -> None:
    """合成成功了一次:记下时间(一年没被合成用过,远端会把它删掉)。"""
    with unit_of_work() as db:
        row = db.get(VoiceEnrollment, copy.id)
        if row is not None:
            row.last_used_at = now()


# ---------------- 列表、删除、重启收尾 ----------------


def copies_by_voice(db: Session, voice_ids: list[str], *, owner_user_id: str) -> dict[str, list[VoiceEnrollment]]:
    """这几把嗓子在**这个人**账号里的副本(配音库每一行显示它在哪儿能念)。别人账号里的那份他用不上,不列。"""
    found: dict[str, list[VoiceEnrollment]] = {}
    if not voice_ids:
        return found
    rows = db.scalars(
        select(VoiceEnrollment)
        .where(VoiceEnrollment.voice_id.in_(voice_ids), VoiceEnrollment.owner_user_id == owner_user_id)
        .order_by(VoiceEnrollment.created_at)
    )
    for row in rows:
        found.setdefault(row.voice_id, []).append(row)
    return found


@dataclass(frozen=True)
class DeleteFailure:
    """一份没删掉的远端副本:在哪条连接、哪个模型上、远端的 id、为什么。"""

    connection: str
    target_model: str
    remote_voice_id: str
    reason: str


def delete_copies(db: Session, voice: Voice) -> list[DeleteFailure]:
    """删掉这把嗓子在各个账号里的副本。删不掉的列出来,**不拦着本机删**(那一行由调用方照删)。

    每个账号用它主人的那把钥匙:副本在谁的账号里,就只有谁的钥匙删得掉。登记了的逐个删;再按前缀列一遍,
    连没登记上的(建到一半进程没了)也一起清掉。
    """
    from app.ai.providers import connection_vendor_for_speech_engine
    from app.domain.providers.selection import resolve_connection

    rows = list(db.scalars(select(VoiceEnrollment).where(VoiceEnrollment.voice_id == voice.id)))
    failures: list[DeleteFailure] = []
    accounts: dict[tuple[str, str, str], list[VoiceEnrollment]] = {}
    for row in rows:
        accounts.setdefault((row.engine, row.provider_profile_id, row.owner_user_id), []).append(row)
    for (engine, profile_id, owner), copies in accounts.items():
        profile = resolve_connection(db, connection_vendor_for_speech_engine(engine), profile_id, user_id=owner)
        if profile is None:
            #: 连接还在就报它的名字(钥匙没了);连接都删了只剩 id。
            gone = db.get(ProviderProfile, profile_id)
            failures.extend(
                DeleteFailure(connection=gone.name if gone is not None else profile_id, target_model=row.target_model,
                              remote_voice_id=row.remote_voice_id, reason="voiceErr_remoteNoConnection")
                for row in copies if row.remote_voice_id
            )
            continue
        account = Account.of(engine, profile, owner)
        adapter = account.adapter()
        targets = {row.remote_voice_id: row.target_model for row in copies if row.remote_voice_id}
        try:
            for one in adapter.list(prefix=prefix_for(voice.id)):
                targets.setdefault(one.voice_id, one.target_model)
        except Exception:  # noqa: BLE001 —— 列不出来就只删登记了的那几个
            logger.info("列不出 %s 在连接 %s 上的远端音色", voice.id, profile_id, exc_info=True)
        for remote_id, model in targets.items():
            try:
                adapter.delete(remote_id)
            except Exception as exc:  # noqa: BLE001 —— 收集起来告诉用户,本机照删
                failures.append(DeleteFailure(connection=account.connection, target_model=model,
                                              remote_voice_id=remote_id, reason=str(exc)[:300]))
    return failures


def reconcile_orphaned_enrollments(db: Session) -> int:
    """重启之后:停在 `deploying`、却还没拿到远端 id 的副本(建之前进程没了)记成失败,下次用到时重建。

    已经拿到 id 的留着 `deploying`:远端那个音色多半已经建好,下次用到时接着等它,不重建第二个。
    """
    rows = list(db.scalars(
        select(VoiceEnrollment).where(VoiceEnrollment.status == DEPLOYING, VoiceEnrollment.remote_voice_id == "")
    ))
    for row in rows:
        row.status = FAILED
        row.error = "voiceErr_remoteEnrollInterrupted"
    return len(rows)


__all__ = [
    "CONSENT_REQUIRED",
    "DEPLOYING",
    "FAILED",
    "MISSING",
    "OK",
    "Account",
    "Copy",
    "DeleteFailure",
    "RemoteConsentRequired",
    "check_voice",
    "clones_remotely",
    "copies_by_voice",
    "delete_copies",
    "ensure_copy",
    "mark_missing",
    "prefix_for",
    "reconcile_orphaned_enrollments",
    "refuse_undeclared",
    "require_consent",
    "speaks_library_voice",
    "start_enrollment",
    "touch",
    "vanished",
]
