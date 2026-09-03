from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.secrets_at_rest import EncryptedJSON, EncryptedText
from app.db.model_base import new_id, now


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    #: 自动放行的准则(见 domain/agent/rules)。带 server_default:迁移语句里写了 DEFAULT,
    #: 模型这边不写的话,**迁移出来的库和新建的库 schema 不一致** —— 同一份代码两种形状,
    #: 而先撞上的往往是一条裸 SQL(测试或以后的运维脚本),报一句看不懂的 NOT NULL 失败。
    #: 下面几个带 DEFAULT 的列同理:http 主机白名单、发布账号白名单、run_code 要不要
    #: 交给判断者、以及一段自由文本。**工作区级**而不是会话级:它是"这个团队允许什么"的策略,
    #: 不是"这次对话想怎么样"的选择 —— 后者是权限模式。
    autopilot_rules: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    #: 他对**这个后端实例**负责吗 —— 网络出口、插件启用、解释器路径、模型下载。
    #:
    #: 此前这件事没有对应物,只能用「在任意工作区里是 owner/admin」去近似,而任何人都能新建
    #: 工作区并在里面是 owner —— 那个近似是**自助的**(ADR 0008 §2.1 有复现)。把它变成数据之后,
    #: 判据不再能被自己造出来。
    #:
    #: **不叫「机器主人」**:共享部署里跑这个后端的人未必是任何一个用户。这说的是谁对这个部署
    #: 负责,不是谁拥有这台机器。库里第一个账号自动持有,之后只能由已有的部署管理员授予。
    is_deployment_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    signature: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 头像文件相对 data_dir 的 key(avatars/<uid>-<ts>.<ext>);空 = 未设置,前端回退首字母。
    avatar_key: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class AuthSession(Base):
    """一份可以用来调这个 API 的凭据 —— 人登录的,和子进程回连用的,是同一张表、同一种权力。

    **每一行都必须会过期。** 此前没有 `expires_at`,于是"用完删掉"是每个铸造点各自的责任:
    对话轮次记得删,工具通道忘了(一次调用留一行),OAuth 刷新/查额度/订阅登录也忘了 ——
    同一个缺陷发作了五次,而漏掉一处不会有任何东西报错。周期由表来保证之后,忘记撤销最多是
    多活一会儿,不再是留下一把永久钥匙。铸造与清理都在 core/security.py。

    `kind` 区分的是**周期的来源**:登录会话的周期是"这个人还在用这台机器"(活跃即续期),
    服务令牌的周期是"那次操作要跑多久"(用得再多也不续)。
    """

    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("idx_auth_sessions_user", "user_id"),
        # 清理按过期时间扫全表;泄漏期攒下的行可能不少,别让它退化成顺序扫描。
        Index("idx_auth_sessions_expires", "expires_at"),
    )

    token: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    #: login(人)| service(子进程回连)。决定要不要滑动续期。
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="login", server_default="login")
    #: 这份凭据属于哪次智能体会话(service 令牌;登录令牌为空)。**确认卡的归属从这里来**——
    #: 归属由凭据决定,不由调用方在请求体里声明,否则任何拿着同一份凭据的通道都能把自己的动作
    #: 挂到一个开了自动放行的会话上。不设外键:会话删掉之后令牌仍要能认出人来(周期结束自然消失)。
    agent_session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    #: 不给默认值:每个铸造点都必须说清这份凭据该活多久,漏了是 IntegrityError 而不是永久有效。
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    #: 这个客户端自报的版本(见 core/permissions.get_current_user)。**必须由客户端报** ——
    #: 后端进程的 app_version 是它自己的版本,回答不了"分布式部署里某个人装的是哪一版",
    #: 而那正是管理员要看的:它解释了为什么只有他撞得到那个早就修好的 bug。
    client_version: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="")
    #: 这份凭据最近一次被用到。管理员据此看"他还在用吗" —— 停用一个账号之前总要先知道这个。
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OAuthIdentity(Base):
    """第三方登录身份(google/apple)→ 本地账号的映射;同一账号可挂多个身份。
    subject 是提供方 id_token 里的稳定用户标识(sub),email 只作展示留痕。"""

    __tablename__ = "oauth_identities"

    provider: Mapped[str] = mapped_column(String(20), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="owner")  # owner|admin|editor|viewer
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class ResourceShare(Base):
    """主人把某样东西放进了某个工作区。**归属与共享是两件事**(见 domain/sharing)。

    此前只有归属这一半的位置(`workspace_id`),而它同时兼任了共享 —— 于是没有「放进来但仍然是
    我的」这种状态,某人的平台登录态、已登录的浏览器、私人对话全都是工作区的公共资产。
    """

    __tablename__ = "resource_shares"
    __table_args__ = (
        UniqueConstraint("kind", "resource_id", "workspace_id", name="uq_resource_share"),
        Index("idx_resource_shares_lookup", "kind", "workspace_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    #: publish_account / browser_profile / agent_session / scheduled_task(见 domain/sharing.KINDS)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    shared_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class RegistrationInvite(Base):
    """**进这个部署**的邀请码 —— 与 WorkspaceInvitation(进某个工作区)是两件事。

    关掉自助注册之后必须有这个:老的邀请流程是「按用户名邀请一个**已注册**账号」,而账号从哪来
    正是被关掉的那条路。两层划分在这里第一次显形 —— 一个是部署的门,一个是工作区的门。

    码是随机串,由管理员带外发给对方;对方拿它注册并**自己设密码** —— 保持仓库既有的那条
    「密码不经过任何第三人之手」(见 domain/members 的说明)。
    """

    __tablename__ = "registration_invites"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    #: 给谁的(仅备注,不做校验)—— 管理员自己看得出这个码发给了谁。
    note: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    used_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class WorkspaceInvitation(Base):
    """工作区邀请(邀请制):受邀人从通知里 接受/拒绝,接受才写成员行。"""

    __tablename__ = "workspace_invitations"
    __table_args__ = (Index("idx_ws_invitations_invitee_status", "invitee_id", "status"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    inviter_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    invitee_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="editor")  # admin|editor|viewer
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending|accepted|declined
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)




class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (Index("idx_projects_workspace_updated", "workspace_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    active_sequence_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)

    sequences: Mapped[list["Sequence"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (Index("idx_assets_workspace_created", "workspace_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="imported")
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(260), nullable=False, default="")
    file_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    media_info: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    tags: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class Voice(Base):
    """A cloned voice = a short reference clip + its transcript. Zero-shot TTS
    engines (F5-TTS / Fish Speech) synthesize new speech in this voice from the
    (reference audio + reference text + target text) triple. Workspace-scoped."""

    __tablename__ = "voices"
    __table_args__ = (Index("idx_voices_workspace_created", "workspace_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    reference_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reference_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="upload")  # upload | speaker
    source_asset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_speaker: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class Lut(Base):
    """A 3D color lookup table (.cube), uploaded per workspace and burned in with
    ffmpeg lut3d at export. Referenced from clip.effects.color.lut by id."""

    __tablename__ = "luts"
    __table_args__ = (Index("idx_luts_workspace_created", "workspace_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(260), nullable=False, default="")
    file_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class Font(Base):
    """A subtitle font file uploaded per workspace. Referenced from sequence.subtitle_style
    by id; the preview loads it over HTTP as an @font-face and export points libass at its
    directory, so preview and burn-in resolve the same family."""

    __tablename__ = "fonts"
    __table_args__ = (Index("idx_fonts_workspace_created", "workspace_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    # Read out of the font's own name table, so it matches what libass will look up by family.
    family: Mapped[str] = mapped_column(String(200), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(260), nullable=False, default="")
    file_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class GeneratedAsset(Base):
    __tablename__ = "generated_assets"

    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Transcript(Base):
    __tablename__ = "transcripts"
    __table_args__ = (Index("idx_transcripts_asset", "asset_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    language: Mapped[str] = mapped_column(String(24), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ready")
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="imported")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    segments: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="transcript", cascade="all, delete-orphan", order_by="TranscriptSegment.start_time"
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (Index("idx_transcript_segments_transcript_start", "transcript_id", "start_time"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    transcript_id: Mapped[str] = mapped_column(ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    speaker: Mapped[str | None] = mapped_column(String(80), nullable=True)

    transcript: Mapped[Transcript] = relationship(back_populates="segments")
    tokens: Mapped[list["TranscriptToken"]] = relationship(
        back_populates="segment", cascade="all, delete-orphan", order_by="TranscriptToken.token_index"
    )


class TranscriptToken(Base):
    __tablename__ = "transcript_tokens"
    __table_args__ = (Index("idx_transcript_tokens_segment_index", "segment_id", "token_index"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    segment_id: Mapped[str] = mapped_column(ForeignKey("transcript_segments.id", ondelete="CASCADE"), nullable=False)
    token_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(String(120), nullable=False)

    segment: Mapped[TranscriptSegment] = relationship(back_populates="tokens")


class ClipTranscriptRef(Base):
    __tablename__ = "clip_transcript_refs"
    __table_args__ = (Index("idx_clip_transcript_refs_clip", "clip_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    clip_id: Mapped[str] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"), nullable=False)
    transcript_id: Mapped[str] = mapped_column(ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False)
    segment_id: Mapped[str | None] = mapped_column(ForeignKey("transcript_segments.id", ondelete="CASCADE"), nullable=True)


class Sequence(Base):
    __tablename__ = "sequences"
    __table_args__ = (Index("idx_sequences_project_updated", "project_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=1920)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=1080)
    fps: Mapped[float] = mapped_column(Float, nullable=False, default=30.0)
    # 改画幅:{fill_mode: cover|contain|blur, scale, x, y};空 = 默认 cover 无平移缩放
    reframe: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    subtitle_style: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)

    project: Mapped[Project] = relationship(back_populates="sequences")
    tracks: Mapped[list["Track"]] = relationship(back_populates="sequence", cascade="all, delete-orphan", order_by="Track.position")


class Track(Base):
    __tablename__ = "tracks"
    __table_args__ = (Index("idx_tracks_sequence_position", "sequence_id", "position"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    sequence_id: Mapped[str] = mapped_column(ForeignKey("sequences.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    muted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    solo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duck: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 有其它音频时压低本轨
    #: 这条轨**是干什么的**,空 = 一条普通轨。目前只有 "dub"(字幕配音落地的地方)。
    #: 不靠名字认:名字是给人看的、可以随便改,而"再配一次要放回同一条轨"必须认得准。
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="")

    sequence: Mapped[Sequence] = relationship(back_populates="tracks")
    clips: Mapped[list["Clip"]] = relationship(back_populates="track", cascade="all, delete-orphan", order_by="Clip.timeline_start")


class Clip(Base):
    __tablename__ = "clips"
    __table_args__ = (Index("idx_clips_sequence_track_start", "sequence_id", "track_id", "timeline_start"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    sequence_id: Mapped[str] = mapped_column(ForeignKey("sequences.id", ondelete="CASCADE"), nullable=False)
    track_id: Mapped[str] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"), nullable=True)
    timeline_start: Mapped[float] = mapped_column(Float, nullable=False)
    src_in: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    src_out: Mapped[float] = mapped_column(Float, nullable=False)
    speed: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    gain: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    muted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    linked_clip_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    text_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    effects: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # 片段变换(缩放/位移/旋转/透明度);空 = 恒等。{scale,x,y,rotation,opacity}
    transform: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)

    track: Mapped[Track] = relationship(back_populates="clips")
    #: 只为读**素材类型**用(界面要判断"这一段转不转得了")。同一条序列里同一个素材反复出现,
    #: 身份映射会把它们收敛成一次查询,所以这里不值得为它加急切加载。
    asset: Mapped["Asset | None"] = relationship(lazy="selectin")

    @property
    def asset_kind(self) -> str:
        return self.asset.kind if self.asset is not None else ""


class SequenceOperation(Base):
    __tablename__ = "sequence_operations"
    __table_args__ = (Index("idx_sequence_operations_sequence_created", "sequence_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    sequence_id: Mapped[str] = mapped_column(ForeignKey("sequences.id", ondelete="CASCADE"), nullable=False)
    revision_before: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_after: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reverted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    undo_of: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class SequenceRevision(Base):
    __tablename__ = "sequence_revisions"
    __table_args__ = (Index("idx_sequence_revisions_sequence_revision", "sequence_id", "revision"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    sequence_id: Mapped[str] = mapped_column(ForeignKey("sequences.id", ondelete="CASCADE"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    render_plan_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


from app.db.model_slices.jobs import Job, TaskEvent  # noqa: E402,F401


from app.db.model_slices.notifications import Notification  # noqa: E402,F401


from app.db.model_slices.scheduler import ScheduledTask, ScheduledTaskRun  # noqa: E402,F401


from app.db.model_slices.workflows import Workflow, WorkflowRevision  # noqa: E402,F401


from app.db.model_slices.boards import Board  # noqa: E402,F401


from app.db.model_slices.publish import PublishAccount, PublishTask  # noqa: E402,F401


from app.db.model_slices.browser import BrowserAction, BrowserProfile, BrowserSession  # noqa: E402,F401


class ProviderProfile(Base):
    """某个人配的一条供应商连接。同一家可以配多条(两个 OpenAI 兼容端点、两把 key)。

    **归建它的那个人。** 曾经是部署级的:任何登录用户都看得见全部连接,而只有部署管理员建得了、
    改得了。理由写的是"怎么连到这家供应商是部署的配置" —— 那在单人机器上成立,在多租户产品里
    不成立,而这个应用是后者。

    代价跑出来过:新账号一进设置页就看到八条别人建的连接,每条底下一行红字「未配置你的密钥」——
    看得见、用不了、也建不了自己的。端点泄露也是同一个根(别人的私有部署地址印在他的列表里),
    当时是遮住地址,那只是打补丁。

    现在钥匙和连接归同一个人,所以它们其实是一件事的两半;ProviderCredential 仍然单独一张表,
    因为它装的是 oauth 令牌、模型目录这些**会变**的东西,而连接是用户填的那份配置。
    """

    __tablename__ = "provider_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    #: 谁的。不设外键、也不做级联:账号删除走 domain/members.delete_account 那条统一的路
    #: (它按 schema 扫所有指向人的列),FK 在这里只会多一种删不掉账号的失败方式。
    owner_user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="", index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    vendor: Mapped[str] = mapped_column(String(60), nullable=False)  # alibaba|bytedance|openai|moonshot|minimax|openai-compatible|...
    base_url: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    #: 鉴权方式。"api_key" = 每个人自己的那把(见 ProviderCredential);"oauth" = 订阅计划
    #: (Claude Pro/Max、Kimi Code 等),密钥同样按人存。哪些方式可用由 ProviderDefinition 声明。
    auth_type: Mapped[str] = mapped_column(String(20), nullable=False, default="api_key")
    #: 这条连接的**非密**附加配置(区域、端点变体等)。密的那几个(火山 ak/sk、快手 secret_key)
    #: 跟着钥匙走,存在 ProviderCredential.secrets 里 —— 哪些字段是密的由 ProviderDefinition 的
    #: `secret: True` 声明,而那也正是渲染表单的同一份声明。
    extra: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class ProviderCredential(Base):
    """某个人在某条连接上的钥匙。

    **为什么钥匙不能待在 ProviderProfile 上**:那张表回答的是「怎么连到这家供应商」——
    端点、模型目录、定价规则,那是部署的配置,由部署管理员维护。而钥匙回答的是「谁在花钱、
    以谁的身份调用」。压在一起的后果跑出来过:能发起一轮对话的人就能 acquire 到那份明文
    凭据,而普通成员又没法带自己的钥匙 —— 订阅制账号(Claude Pro/Max)被多人共用,供应商
    那边看到的是同一个账号。

    **没有"共享钥匙"这回事**:每个人配自己的。曾经有过一个 `shared` 位,是为了让升级无缝 ——
    但它没有任何界面(等于隐藏状态),而且和这张表存在的理由自相矛盾:钥匙归人,正是为了不再
    「所有人共用一把、花的是同一个人的钱」。
    """

    __tablename__ = "provider_credentials"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("provider_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    api_key: Mapped[str] = mapped_column(EncryptedText, nullable=False, default="", server_default="")
    #: pi 的 Credential **原样**存放({type, access, refresh, expires, ...})。刻意不拆成列:
    #: 各家 OAuth 的附加字段(Copilot 的 endpoint、Codex 的 account_id)由 pi 自己解释,
    #: 这边拆一次就等于把各家协议复制进 Python,下次上游加字段就悄悄丢了。
    oauth_credential: Mapped[dict | None] = mapped_column(EncryptedJSON, nullable=True, default=None)
    #: ProviderDefinition 里标了 `secret: True` 而又不落 api_key 的那几个(火山 ak/sk、快手 secret_key)。
    secrets: Mapped[dict] = mapped_column(EncryptedJSON, nullable=False, default=dict, server_default="{}")
    #: 订阅计划登录后拿到的可用模型目录([{id, name, contextWindow, maxTokens}])。跟着钥匙走:
    #: 它是**这次登录**的结果 —— Copilot 的模型随订阅档位变,两个人的订阅目录可以不一样。
    model_catalog: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)
    #: 乐观并发版本号。多个会话可以同时开对话,各自 spawn 一个 sidecar;若两个同时刷新
    #: 同一份 OAuth 凭据,后写的会把已被服务端轮换作废的 refresh token 覆盖回去 ——
    #: 表现为用户莫名其妙被登出。写入时带上读到的版本,不匹配就拒绝(见 credentials 路由)。
    credential_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class ProviderModel(Base):
    """一条连接下的一个模型。

    **为什么模型必须是一等实体**:此前「档案」的粒度是不一致的 —— 有的是一条连接(一个端点
    多个模型),有的其实是一个模型(用户拿模型名当档案名建了 gpt-image-2、火山seedream)。
    用户被迫这样,是因为能力挂在档案上、而档案只有一个 default_model:想用同一个端点的两个
    模型做两件事,就只能建两个档案。

    能力下沉到模型这一层之后,一条连接可以同时提供对话模型和生图模型,「某能力的默认模型」
    也才有东西可指 —— ProviderDefault 早就是 (capability → profile + model) 的形状,
    只是没有模型实体可以引用。

    **表里存的是"已配置的模型",不是模型全集**。供应商目录仍是发现来源(见 ai.model_catalog
    与订阅计划的 model_catalog),界面把两者合并展示:目录有而这里没有 = 未配置,可一键加入;
    这里有而目录没了 = 标记"目录中已不存在"但不删,别名与私有部署仍要能用。
    """

    __tablename__ = "provider_models"
    __table_args__ = (
        # 同一条连接下模型 id 唯一 —— 否则"哪一行是这个模型"就没有答案了。
        UniqueConstraint("provider_profile_id", "model_id", name="uq_provider_models_profile_model"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    provider_profile_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("provider_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: 发给供应商的模型标识,原样。
    model_id: Mapped[str] = mapped_column(String(160), nullable=False)
    #: 展示名。留空即用 model_id —— 大多数情况下模型 id 本身就是最好的名字。
    display_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    #: 这个模型能干什么(chat / image / video / tts / podcast)。**能力在模型上而不是连接上**:
    #: 同一个端点既有对话模型也有生图模型,挂在连接上就只能二选一。
    capability_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    #: 停用的模型不出现在任何选择器里。OpenRouter 几百个模型全铺进下拉是不可用的。
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: catalog = 来自供应商目录;manual = 用户手填(私有部署、别名,目录里查不到)。
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="catalog")

    #: 以下是"我对这个模型做过什么"。**留空表示跟随目录/保守默认**,不是 0/False ——
    #: 两者混淆会让"没设过"被当成"显式设成了关"。
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    #: 都对应 pi 里真实生效的开关(思考格式 / 图片输入 / reasoning_effort / developer 角色)。
    reasoning: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    vision: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    reasoning_effort: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    developer_role: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)

    #: 解析一个模型时几乎总要同时拿到端点与凭据 —— 它们在连接上。
    profile: Mapped["ProviderProfile"] = relationship(lazy="joined")


class ProviderDefault(Base):
    """某个人在某种能力下默认用哪个模型。

    capability:chat / image / video / tts / podcast。用到该能力且未显式指定时取此默认。

    **默认模型是个人偏好,不是部署配置**:同一条连接,两个人完全可以各自默认不同的模型。此前它
    只按 capability 建行、且要部署管理员才能改 —— 那是把「钥匙归人」那把尺子没量到底(ADR 0008
    D3 的同一条道理)。

    **没有"部署默认"这一档。** 曾经有过一行 `owner_user_id=""` 当作"还没设过的人的起点",
    删掉了(见 domain/provider_defaults.get_row):它看起来温和 —— 只在你没设时生效 —— 但造成的
    正是这个应用里反复出现的那种误解:界面上你没选过任何模型,回答却来自某个你不知道的模型,
    花的是你的额度、用的是你的钥匙。没设就说没设。

    `owner_user_id` 用空串而不是 NULL 作默认值,是因为 SQLite 允许 PRIMARY KEY 列为 NULL ——
    那会让同一个人的同一项能力可以重复插入而不报错。
    """

    __tablename__ = "provider_defaults"

    capability: Mapped[str] = mapped_column(String(24), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), primary_key=True, default="", server_default="")
    #: 指向具体的模型行 —— 一件事只存一处。此前这里还并存着 (provider_profile_id, model)
    #: 那一对:模型还不是实体时的写法。两份会漂移的真相里总有一份是错的,已删。
    provider_model_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("provider_models.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class ProviderPricingRule(Base):
    """Versioned price rule for one provider capability.

    Pricing is deliberately outside ProviderProfile: a profile tells Mosael how to call an
    Adapter, while this table tells the usage Module how to estimate spend for a metered unit.
    """

    __tablename__ = "provider_pricing_rules"
    __table_args__ = (
        Index("idx_provider_pricing_lookup", "workspace_id", "provider_profile_id", "provider", "capability", "model"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True)
    provider_profile_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("provider_profiles.id", ondelete="CASCADE"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    capability: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    billing_unit: Mapped[str] = mapped_column(String(40), nullable=False)
    unit_amount_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    effective_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class ProviderUsageEvent(Base):
    """Immutable-ish metering row for a billable provider interaction.

    Task events are good for timeline display but may be pruned; this table is the durable audit
    fact source. Callers create rows through app.domain.usage, never directly.
    """

    __tablename__ = "provider_usage_events"
    __table_args__ = (
        Index("idx_provider_usage_workspace_created", "workspace_id", "created_at"),
        Index("idx_provider_usage_job", "job_id"),
        Index("idx_provider_usage_agent_message", "agent_message_id"),
        Index("uq_provider_usage_idempotency", "idempotency_key", unique=True),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    provider_profile_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("provider_profiles.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    capability: Mapped[str] = mapped_column(String(40), nullable=False)
    operation: Mapped[str] = mapped_column(String(60), nullable=False)
    source_type: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    source_id: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    agent_message_id: Mapped[str | None] = mapped_column(ForeignKey("agent_messages.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="succeeded")
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    units: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    raw_usage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    cost_micros: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    cost_confidence: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    pricing_rule_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("provider_pricing_rules.id", ondelete="SET NULL"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)



class AiRuntimeConfig(Base):
    """Singleton (id='default') 运行时 AI 设置。目前只含「供应商瞬断时的最大重试次数」
    (0..10,缺省 3),用户可在设置页调整——见 workflows/executors/ai.py。"""

    __tablename__ = "ai_runtime_config"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default="default")
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class DeploymentConfig(Base):
    """Singleton (id='default') 部署级开关 —— **这台后端**怎么对外。

    为什么进库而不是留在环境变量里:改它是部署管理员在界面上就该能做的决定(和发邀请码、
    授予管理员同一类),而环境变量意味着要能碰到部署机、要重启进程。

    **库是唯一真相**;环境变量只在首次迁移时播一次种(见 core/db._migrate_deployment_config),
    之后不再读 —— 不做"两边都读"的兼容,那样一个部署会同时有两个答案,而谁赢取决于代码里的顺序。
    """

    __tablename__ = "deployment_config"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default="default")
    #: 陌生人能不能自己建账号。关掉之后要邀请码(见 routes/auth.register)。
    open_registration: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    #: 插件市场的索引地址。空 = 用内置默认(见 domain/plugins/registry)。
    #:
    #: 是部署级设置而不是每人一份:装插件是把代码放进**这台机器**,而这台机器上装了什么
    #: 对所有用户是同一件事。公司内网可以指向自己那一份。
    plugin_registry_url: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class NetworkConfig(Base):
    """Singleton (id='default') 出站网络代理。

    空 proxy_url = 直连。一处配置,后端 httpx / sidecar / 内嵌浏览器都遵守 —— 见
    app/domain/network.py(里面也说明了为什么回环永远不走代理)。
    """

    __tablename__ = "network_config"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default="default")
    #: 形如 http://127.0.0.1:7890 或 socks5://127.0.0.1:1080;空串 = 直连。
    proxy_url: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    #: 额外绕过代理的主机,逗号分隔。默认值由领域层在建行时填(模型层不该反向依赖 domain),
    #: 回环则由代码强制补上、不依赖这里填对 —— 两者都见 app/domain/network.py。
    no_proxy: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class TtsConfig(Base):
    """Singleton (id='default') runtime config for voice cloning: which engine,
    the external interpreter that has f5-tts/fish-speech installed, and the model
    download source. Overrides the MOSAEL_TTS_* env fallback so it's UI-editable."""

    __tablename__ = "tts_config"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default="default")
    engine: Mapped[str] = mapped_column(String(32), nullable=False, default="f5-tts")  # f5-tts | fish-speech
    python_path: Mapped[str] = mapped_column(String(500), nullable=False, default="")  # empty = autodetect
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="hf-mirror")  # hf | hf-mirror | modelscope
    #: 装引擎依赖(torch 等 2.5–3.5GB)时用的 pip 索引。空 = 官方 PyPI。
    #: 与 source 分开:那个管模型权重从哪拉(HuggingFace),这个管 Python 包从哪拉。
    pip_index: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Fish Speech runs from a source checkout + a local weights dir (with codec.pth);
    # empty = fall back to the app-managed install. See domain/tts_config.py.
    fish_repo_dir: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    fish_model_dir: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class GenerationSession(Base):
    __tablename__ = "generation_sessions"
    __table_args__ = (Index("idx_generation_sessions_ws_updated", "workspace_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    #: 谁的(见 domain/sharing)。生成会话和对话一样是**某人的私人工作线程**,默认只有自己看得见。
    owner_user_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="新生成")
    #: 收在哪个分组里(SessionGroup.kind == "generation")。和对话同一条规矩:不设外键,
    #: 分组被删时由 domain/session_groups 显式清空 —— 收纳方式不该反过来决定会话的生死。
    group_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    provider_profile_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("provider_profiles.id", ondelete="SET NULL"), nullable=True
    )
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    kind: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)

    generations: Mapped[list["GenerationJob"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="GenerationJob.id"
    )


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("generation_sessions.id", ondelete="CASCADE"), nullable=True
    )
    # SET NULL 而非 CASCADE:生成记录是创作历史,不能陪着任务中心的「清空已完成」
    # 一起蒸发(曾经就是这么丢的)。job 没了记录仍在,状态由 result_asset_id 兜底。
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    provider_profile_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("provider_profiles.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    request: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)

    session: Mapped[GenerationSession | None] = relationship(back_populates="generations")


#: 分组挂在哪一种会话上。两边**各自一套**:对话里建的「客户 A」不会跑到生成栏里去空着站着。
SESSION_GROUP_KINDS = ("agent", "generation")


class SessionGroup(Base):
    """会话分组:给会话列表分个类,便于管理。对话和生成共用这张表,由 `kind` 分开。

    **是一张表而不是会话上的一个名字字符串**:分组要能空着存在(先建「客户 A」,再往里挪会话),
    改名要是一次操作而不是把 N 行的字符串挨个改一遍 —— 名字当键的话,这两件事都做不到。

    删掉分组**不删里面的会话**(先把成员的 group_id 清空):分组是收纳方式,不是所有权。
    """

    __tablename__ = "session_groups"
    __table_args__ = (Index("idx_session_groups_ws_kind", "workspace_id", "kind"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    #: "agent" | "generation" —— 见 SESSION_GROUP_KINDS。
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default="agent")
    #: 谁建的。和会话同一条规矩:不设外键,账号没了归属仍是审计信息。
    owner_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    #: 手动排序位。越小越靠前;相同就按建立时间。
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class AgentSession(Base):
    __tablename__ = "agent_sessions"
    __table_args__ = (Index("idx_agent_sessions_ws_updated", "workspace_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    #: 这是谁的。**不设外键**:账号被删时这份东西的归属仍然是审计信息,不该级联消失
    #: (归属与共享见 domain/sharing)。
    owner_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    #: 收在哪个分组里。空 = 未分组(列表里单独一段)。删分组时由路由显式清空 —— 老库那一列
    #: 是迁移加的、没有外键约束,不能指望数据库替我们 SET NULL。
    group_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="新对话")
    origin: Mapped[str] = mapped_column(String(24), nullable=False, default="ui")  # ui | feishu
    external_key: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    #: 跑这次会话的运行时。目前只有 "pi";留列是为了旧会话仍能被正确解读。
    adapter: Mapped[str] = mapped_column(String(40), nullable=False, default="pi")
    # 对话用的供应商 + 模型(pi 适配器);空则回退第一个启用供应商及其默认模型
    provider_profile_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("provider_profiles.id", ondelete="SET NULL"), nullable=True
    )
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # 视频分析方式偏好:auto(默认,原生优先否则抽帧)/ native(强制原生)/ frames(强制抽帧+转写)。
    # 会话级,聊天里可切,注入系统提示让 analyze_asset 照此传 mode。
    analysis_video_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")
    #: 权限模式:manual(默认)/ auto / bypass。挂在**会话**上 —— 「这次对话里哪一类动作不用问我」
    #: 是每次对话的选择,和思考档位同类。
    permission_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="manual", server_default="manual")
    #: 模式是**谁**开的。行动人不是他就退回手动:飞书群聊共用一个会话,群里任何人发消息都跑在
    #: 同一个会话上 —— 没有这一条,A 开的 bypass 会替 B 做决定。而会话本身不记 owner。
    #: 谁开的这个模式。**不能用 owner_user_id 顶替**(ADR 0008 D6 曾经提过这个简化):会话可以
    #: 被共享,共享之后别的成员也能改模式 —— 那时"谁开的"与"谁的会话"是两个人,而模式是一次
    #: **授权动作**,只对做出授权的那个人生效。合并两列等于把一个人的授权悄悄转给另一个人。
    mode_set_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 开启时刻。计费卡「连续自动放行几张」从这里起算。
    mode_set_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: 「本会话始终允许」的工具名。此前是浏览器 localStorage 里的一份自动批准 —— 聊天面板一关
    #: 组件就卸载,而 turn 还在跑,同一个"授权"的行为取决于某个 React 组件在不在。
    auto_allow_tools: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    #: 思考档位(off/low/medium/high)。挂在**会话**上而不是模型上:同一个模型有时要深想、
    #: 有时要快答,它是每次对话的选择。off 时 pi 根本不向供应商要思考。
    thinking_level: Mapped[str] = mapped_column(String(10), nullable=False, default="off")
    #: 当前任务计划:`[{"step": "...", "status": "pending|in_progress|done"}]`。
    #: 挂在会话上而不是单独建表 —— 一次会话只有一份"现在在做什么",历史进度由 update_plan
    #: 的工具卡在时间线上留痕,不需要第二套版本记录。
    plan: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    # pi 适配器无 --resume:存 pi 序列化的消息数组做多轮记忆(下轮回灌 initialState.messages)
    adapter_state: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="idle")  # idle | running
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)

    messages: Mapped[list["AgentMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="AgentMessage.created_at"
    )


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (Index("idx_agent_messages_session_created", "session_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    session: Mapped[AgentSession] = relationship(back_populates="messages")


class AgentMemory(Base):
    """跨会话记忆:一条关于"这个工作区里该知道的事"的短事实。

    记忆是**每轮都注入系统提示**的行为约定,不是需要临时检索的外部资料 ——
    "视频统一 1080p 竖屏"、"片头永远用 brand-intro.mp4"、"客户叫我别用红色"。
    参考 Claude Code 的 CLAUDE.md / Codex 的 AGENTS.md:它们的价值恰恰在于不用检索也生效。

    **两级作用域**:workspace_id 必填(记忆跟着工作区走),project_id 可空 —— 填了就只在
    那个项目的会话里注入。这对应 Claude Code 的"用户级 / 项目级"两层。
    """

    __tablename__ = "agent_memories"
    __table_args__ = (Index("idx_agent_memories_ws", "workspace_id", "project_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    #: agent = 智能体自己记下的;user = 用户在设置里写的。用户写的排在前面注入。
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="agent")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class FeishuBot(Base):
    __tablename__ = "feishu_bots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False, default="Mosael 助手")
    app_id: Mapped[str] = mapped_column(String(120), nullable=False)
    app_secret: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    capability: Mapped[str] = mapped_column(String(24), nullable=False, default="editor")  # readonly|editor|full
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="offline")  # offline|connecting|online|error
    status_detail: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class FeishuBinding(Base):
    """Binds a Feishu sender (open_id) to a Mosael account within a workspace, so the bot
    acts with THAT member's permissions instead of a blanket owner identity."""

    __tablename__ = "feishu_bindings"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    open_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class FeishuBindCode(Base):
    """One-time code a member issues in-app and sends to the bot from Feishu to bind their open_id."""

    __tablename__ = "feishu_bind_codes"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AgentQuestion(Base):
    """智能体问用户一个有选项的问题,等他挑。

    **不是确认卡。** 确认卡问的是「这件事能不能做」,而这里问的是「你要哪一个」——
    形状像,但有一条决定性的差别:确认卡有 `auto_allow_tools` 和 bypass 模式,可以被
    自动批准;而询问的**全部意义就是智能体不知道答案**,自动回答等于让它自己编一个。
    共用一张表的话,那两个开关迟早会把问题一起自动答掉。

    只在对话里出现(session_id 必填):一个问题脱离了它的上下文没有意义 —— 右上角的
    全局中心里蹦出一句「你要哪一个」,而看的人根本不知道在说什么。
    """

    __tablename__ = "agent_questions"
    __table_args__ = (Index("idx_agent_questions_session", "session_id", "status"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    #: 哪次对话问的。不设外键:会话删了这条记录的归属仍有审计意义。
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: [{header, question, multi_select, options: [{label, description}]}]
    questions: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    #: {question: [选中的 label]}。多选也是列表 —— 单选是"长度为 1 的列表",
    #: 两种形状分开存的话,消费端要写两遍解析。
    answers: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    #: pending | answered | dismissed
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ToolConfirmation(Base):
    __tablename__ = "tool_confirmations"
    __table_args__ = (
        Index("idx_tool_confirmations_ws_status", "workspace_id", "status"),
        Index("idx_tool_confirmations_session", "session_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    #: 发起这张确认卡的智能体会话。**可空**:MCP / 飞书等外部智能体没有会话,它们的卡由右上角
    #: 全局确认中心兜底。有会话的卡只在**它自己那次对话**里内联出现 —— 否则同工作区的其它对话会
    #: 把它显示出来,更糟的是会被那边的「本会话始终允许」自动批准(授权范围逃逸)。
    #: 不设外键:会话删除后这张卡的归属仍然有意义(审计),也不该级联删掉历史。
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=False)
    tool: Mapped[str] = mapped_column(String(80), nullable=False)
    permission: Mapped[str] = mapped_column(String(40), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str] = mapped_column(String(120), nullable=False, default="external-agent")
    #: 这张卡是**怎么**过的:manual(人点的)/ session-allow(工具白名单)/ auto / bypass。
    #: 自动放行必须留痕,而且要能一眼看出是哪一档放的 —— 事后能查是 bypass 唯一可接受的前提。
    decision_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="manual", server_default="manual")
    #: 记在谁头上。自动放行也有人 —— 那次 turn 是以他的身份跑的,授权闸也是按他校验的。
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 判定依据:档位、计数快照、规则命中、判断者的输入与裁决。
    #: 判定是 (工具, 参数, 准则) 的纯函数,把输入记下来,事后就能复算"当时为什么放行"。
    decision_detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    #: 在这之前先别打扰用户 —— 隔离判断者正在看这张卡(见 domain/agent/autopilot)。
    #: 用**会自己到期的时间**而不是一个"判定中"状态:状态要有人去回收,期限不用 —— 进程崩在判断
    #: 中间,期限自己过去,卡自己回到待办。与 AuthSession 的过期同一种做法。
    hold_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PluginPackage(Base):
    """磁盘上的一个插件目录 + 它的 manifest。**没有「启用」状态** —— 启用的是实例。

    包与实例分开,是因为一个包可以被接入多次:TikHub 一个包对应十几个平台端点,B站一个
    实例、抖音一个实例,各有各的凭据和显示名。此前包和接入是同一行记录,于是"平台"只能
    是一个凭据,而包名写死在 manifest 里 —— 用户配了 bilibili,面板上仍然写着「抖音」。
    """

    __tablename__ = "plugin_packages"

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class PluginInstance(Base):
    """一次具体接入:包 + 一组配置 + 一个显示名 + 启用开关。凭据与授权都挂在这里。

    显示名默认由包的 name_template 从配置生成(「TikHub · 哔哩哔哩」),用户可以改。
    """

    __tablename__ = "plugin_instances"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    #: 谁接的。**包是这台机器装了什么(部署级),接入是某个人用他的账号连上了它。**
    #: 此前整份都是部署级:管理员配一次,所有人的智能体共用那一把第三方密钥 —— 于是用量算不到
    #: 人头上,而新账号一进插件页就看到别人接好的一排。和供应商连接同一条(见 ProviderProfile)。
    owner_user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="", index=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("plugin_packages.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: 明文配置(枚举 / 文本 / 数字 / 开关)。凭据不在这里 —— 那是 PluginCredential。
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    #: MCP 实例的工具清单从服务现拉,缓存在这里(进程类插件写在 manifest 里,此列为空)。
    discovered_tools: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class PluginCapability(Base):
    """这个实例的某个工具暴不暴露给智能体和工作流。**默认不暴露**。

    一个 MCP 端点报几十上百个工具(TikHub 的 bilibili 报了 41 个)。全量涌进节点面板和
    智能体工具表,面板要人从四十行里找一行,工具表让每轮对话为四十条描述付 token 并挤占
    模型在内置工具之间的选择权。要人从四十个里挑出该关的三十七个,没有人会做 ——
    默认值就是实际行为,所以默认关,由 manifest 的 recommended 给一个起点。
    """

    __tablename__ = "plugin_capabilities"

    instance_id: Mapped[str] = mapped_column(ForeignKey("plugin_instances.id", ondelete="CASCADE"), primary_key=True)
    tool_name: Mapped[str] = mapped_column(String(160), primary_key=True)
    exposed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PluginPermissionGrant(Base):
    __tablename__ = "plugin_permission_grants"

    instance_id: Mapped[str] = mapped_column(ForeignKey("plugin_instances.id", ondelete="CASCADE"), primary_key=True)
    permission: Mapped[str] = mapped_column(String(120), primary_key=True)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class PluginCredential(Base):
    """一个实例自己的凭据(API Key 等),按 manifest 的 `credentials` 声明逐条存。

    **为什么插件不能共用应用的供应商凭据**:插件运行时只向子进程透传 PATH/HOME/LANG,
    刻意不给任何应用凭据——插件因此绕不过确认卡和权限系统。但"什么都不给"也意味着任何
    需要 API Key 的插件只能自己在插件目录里放一个 config.json,让用户开终端去 cp 文件。
    这张表是那个缺口的补丁:**只把该实例自己声明的那几个键**注入它自己的进程环境。

    落盘加密,和 provider_credentials 一致(见 core/secrets_at_rest)—— 主密钥取环境变量,
    取不到才落到数据目录里那个 0600 文件。后一种情况下整个数据目录被一起拷走时加密不起作用,
    这一点如实降级,不假装解决了。

    **归属和 provider_credentials 不一样**:这把钥匙挂在**实例**上,不挂在人身上。插件实例本身
    就是部署级配置(增删改全在 ensure_deployment_admin 后面),所以它的钥匙是这个部署的钥匙 ——
    任何成员的智能体调这个插件工具时,用的都是管理员配的那一把。这是有意的:插件是"这台部署
    装了什么",不是"我是谁";但它确实意味着**用量算不到人头上**,和供应商调用不同。
    """

    __tablename__ = "plugin_credentials"

    instance_id: Mapped[str] = mapped_column(ForeignKey("plugin_instances.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(EncryptedText, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class PluginInvocation(Base):
    __tablename__ = "plugin_invocations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    instance_id: Mapped[str] = mapped_column(ForeignKey("plugin_instances.id", ondelete="CASCADE"), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="running")
    input: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
