"""Isolate every test process in a throwaway data dir BEFORE app modules import.

Without this, reset_db() would drop tables in the developer's live
~/.mosael/mosael.db. Environment variables outrank .env in pydantic-settings,
so setting MOSAEL_DATA_DIR here is sufficient.

**One data dir per process, and under pytest-xdist that means one per worker.** Everything the app keeps on disk
hangs off `settings.data_dir` — the SQLite DB, media, plugin installs and their data, local-service pid files,
skills, run logs — and `settings` is built once, at import, from this variable. Each xdist worker is its own
interpreter that imports this file before any app module, so it gets its own directory (named after the worker,
`mosael-test-gw3-…`, so a leftover one says whose it was) and the workers never share a database or a file.
The directory is removed when the process finishes (see `pytest_unconfigure`); before that every run left one
behind in the system temp dir — a few dozen MB each, gigabytes after a week.
"""

from __future__ import annotations

import os
import shutil
import tempfile

#: "gw0", "gw1", … under `pytest -n`; unset in a plain serial run.
_WORKER = os.environ.get("PYTEST_XDIST_WORKER", "")
_DATA_DIR = tempfile.mkdtemp(prefix=f"mosael-test-{_WORKER}-" if _WORKER else "mosael-test-")
os.environ["MOSAEL_DATA_DIR"] = _DATA_DIR
# Tests drive the scheduler tick() directly; the background loop stays off.
os.environ["MOSAEL_SCHEDULER_ENABLED"] = "0"
# 两个部署级开关在**测试里**打开:整套用例早于它们存在,而且要覆盖的正是它们背后的行为
# (自由注册第二个用户、工作流的 code 节点)。开关自己的用例
# (test_registration_and_code_execution.py)显式把它们按回生产默认值,并单独断言**声明的默认值**
# 是关的 —— 这样"默认关"这件事不会因为测试环境开着而失去保护。
os.environ["MOSAEL_OPEN_REGISTRATION"] = "1"
os.environ["MOSAEL_SERVER_SIDE_CODE_EXECUTION"] = "1"
os.environ["MOSAEL_FEISHU_AUTOSTART"] = "0"
# Don't spawn ffmpeg proxy threads on every video import during the suite;
# test_proxy.py re-enables it explicitly to exercise the pipeline.
os.environ["MOSAEL_GENERATE_PROXIES"] = "0"
# Force software (libx264+CRF) export so render output is deterministic and we
# don't depend on a hardware encoder being present on the CI/dev box.
os.environ["MOSAEL_HW_ENCODE"] = "0"
# Don't launch a headless Chromium to rasterize subtitles/花字 in the suite; the ASS
# fallback path stays exercised and tests don't depend on Playwright/dist being present.
os.environ["MOSAEL_TEXT_RASTERIZE"] = "0"
# 开发机 shell 里的代理变量不带进测试套(CI 上本来就没有)。后端会按库里的网络设置改写本进程的这几个变量
# (domain/network.apply_to_process),于是此前一条测试看不看得见代理,取决于同一个进程里**之前**有没有哪条
# 测试走过那段 —— 换个跑法(并行、换顺序)就换一批测试经代理出网。
for _proxy_variable in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
    os.environ.pop(_proxy_variable, None)
    os.environ.pop(_proxy_variable.lower(), None)

import threading
import time

import pytest

#: 真的钟。测试的桩撤掉之前 conftest 自己要量时间时用它:有的测试把全局的 `time.monotonic` 换掉了(见 _background_work_…)。
_real_monotonic = time.monotonic


def pytest_configure(config) -> None:
    """开关式的「线程起步随机推后」:默认不开,见 tests/thread_jitter.py。"""
    from tests import thread_jitter

    thread_jitter.install_from_env()


def pytest_report_header(config) -> str | None:
    from tests import thread_jitter

    return thread_jitter.header()


def _runs_tests_here(session) -> bool:
    """这个进程自己跑测试:xdist 的 worker,或者不分发时的那一个进程。分发的那个(dsession)只管派活,它起的是 worker。"""
    return not session.config.pluginmanager.has_plugin("dsession")


def pytest_sessionstart(session) -> None:
    if _runs_tests_here(session):
        from tests import child_processes

        child_processes.track()


def pytest_sessionfinish(session) -> None:
    """测试都收完了还在跑的子进程,连同它们的进程组一起收掉(见 tests/child_processes.py)。

    各条测试自己会收它起的服务、插件;这里兜的是半路失败、忘了收、被 Ctrl-C 打断的那些 —— 起在新会话里的子进程收不到
    发给测试进程的信号,此前就这么以 1 号进程为父一直挂着。
    """
    if _runs_tests_here(session):
        from tests import child_processes

        child_processes.sweep()


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_auto_num_workers(config) -> int | None:
    """`-n auto` 写在 pyproject 的 addopts 里:跑全套(或整个目录)时按核数开 worker,点名了文件或某一条用例时
    不分发,就在本进程里跑 —— print、`--pdb`、断点和以前一样,也不用为一条用例起十几个进程。

    返回 None 交给 xdist 自己按核数定(它也认 `PYTEST_XDIST_AUTO_NUM_WORKERS`);给了具体数字(`-n 4`)的
    命令行不经过这里。只想跑一部分但要并行,就写数字。
    """
    root = config.invocation_params.dir
    targets = [arg for arg in config.args if not arg.startswith("-")]
    if targets and all("::" in arg or (root / arg).is_file() for arg in targets):
        return 0
    return None


def pytest_unconfigure(config) -> None:
    """进程结束时删掉这个进程的数据目录。

    后台还可能有没收尾的守护线程往里写(SQLite 的日志文件一建一删),删到一半目录又不空了 —— 所以再试两次;
    还删不掉的忽略,剩下的那点由系统清临时目录时带走,不该让一次清理失败把已经跑完的测试结果变红。
    """
    for _ in range(3):
        shutil.rmtree(_DATA_DIR, ignore_errors=True)
        if not os.path.exists(_DATA_DIR):
            return
        time.sleep(0.2)


@pytest.fixture(scope="session", autouse=True)
def _every_process_starts_with_the_current_schema():
    """每个进程(xdist 的每个 worker)一起来就把库建成当前的形状,不等哪条测试碰巧先调 `fresh_client()`。

    此前库只在 `fresh_client()` 里建。不调它、却经过已装好的缝读库的测试(起 sidecar 时由 `app.main` 导入期装上的
    「子进程代理从库里读」,见 ai/sidecar/pi_client.use_proxy_source)只要是这个 worker 第一条碰库的,就是
    `no such table: network_config` —— 而 xdist 收集时每个 worker 都把所有测试文件导入一遍,`app.main` 总是在的。
    红不红看切块边界落在哪,`-n` 换个数就换一批;点名跑两个文件(`pytest tests/test_pi_turn_lifecycle.py
    tests/test_agent_queue.py`)则必红。这里只保证**表在**;要干净的库照旧调 `fresh_client()`。
    """
    from app.db.migrations import init_db

    init_db()


#: 测试函数体里起的线程,测试连同它的 fixture 都收完之后,最多再等这么久让它们自己结束。
_STRAY_THREAD_GRACE_SECONDS = 10.0
#: 本来就活到进程结束的后台线程(按线程 target 的名字认):本机合成 / 识别常驻进程池的回收线程,池子是进程级的。
_PROCESS_LIFETIME_THREAD_TARGETS = ("_reap_idle",)
_THREADS_BEFORE_BODY = pytest.StashKey[set]()


def _lives_for_the_process(thread: threading.Thread) -> bool:
    return any(f"({target})" in thread.name for target in _PROCESS_LIFETIME_THREAD_TARGETS)


def _let_the_body_threads_finish(item) -> list[threading.Thread]:
    """等这条测试函数体里起的线程自己结束(最多 `_STRAY_THREAD_GRACE_SECONDS`),交回还活着的那些。函数体没跑过就什么都不等。"""
    before = item.stash.get(_THREADS_BEFORE_BODY, None)
    if before is None:  # 函数体没跑(setup 就失败了、被跳过)
        return []
    stray = [t for t in threading.enumerate() if t not in before and t.is_alive() and not _lives_for_the_process(t)]
    deadline = _real_monotonic() + _STRAY_THREAD_GRACE_SECONDS
    for thread in stray:
        thread.join(max(0.0, deadline - _real_monotonic()))
    return [thread for thread in stray if thread.is_alive()]


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item) -> None:
    #: 记在 junit 里:这条跑在哪个 worker 上。一条随机红的测试,常常是同一个 worker 里排在它前面的那条留下了东西
    #: (库里的行、没收的线程)—— CI 传上来的报告里按 worker 一筛,就是它前面跑过的那一串。
    item.user_properties.append(("xdist_worker", os.environ.get("PYTEST_XDIST_WORKER", "main")))


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_call(item) -> None:
    item.stash[_THREADS_BEFORE_BODY] = set(threading.enumerate())


@pytest.hookimpl(wrapper=True, trylast=True)
def pytest_runtest_teardown(item, nextitem):
    """**谁起的线程谁收。** 测试函数体里起的线程,测试和它的 fixture 都收完之后还活着,就让**这一条**在 teardown 红。

    此前这种线程活过测试本身,在后面某条测试 drop_all 的空当里查库、抛异常 —— pytest 把线程里的异常
    (`PytestUnhandledThreadExceptionWarning`,pyproject 里升成了错误)记在**当时恰好在跑的那条**头上:红的是无辜的,
    肇事的那条早就绿着走了。实测:一条测试用 `with fresh_client()` 跑了整个 app lifespan,留下「保持运行」那条线程,
    线程起步稍晚一点(tests/thread_jitter.py),它就在几条之后的 test_agent_first_token 里报 `no such table: local_services`。

    只看函数体里起的(fixture 在 setup 里起、按自己的作用域收的不算);给 `_STRAY_THREAD_GRACE_SECONDS` 让它们自己走完;
    进程级常驻的按 `_PROCESS_LIFETIME_THREAD_TARGETS` 放过。
    """
    result = yield
    alive = [thread.name for thread in _let_the_body_threads_finish(item)]
    if alive:
        raise AssertionError(
            f"这条测试起的线程在它结束 {_STRAY_THREAD_GRACE_SECONDS:g} 秒后还活着:{alive} —— 它们会在后面别的测试里"
            "读写重建中的库、把异常记到无辜的测试头上。在测试里等它们结束(放行替身、join),或者别起它们。"
        )
    return result


@pytest.fixture(autouse=True)
def _every_test_starts_from_the_same_process_state():
    """每条测试从同样的语言、同样的环境变量起步,跑完还原。

    这两样都是本进程里的「当前值」,测试之间没人还原:
      - 语言是 ContextVar,而测试都在主线程里跑 —— 一条测试 `set_current_locale("en")` 之后没改回来,后面这个
        进程里的每一条都在说英文;
      - 环境变量有被后端自己改写的(上面说的代理那几个),也有测试顺手改了没还的。
    单进程按文件顺序跑时,总有后面某条测试碰巧把它们改回去,于是一直看不出来;并行之后每个 worker 分到的用例
    不一样,中招的就变成了随机的一批「中文报错断言拿到英文」。在这里统一还原,而不是去改每一条忘了还原的测试。
    """
    from app.core.i18n import DEFAULT_LOCALE, set_current_locale

    environ = os.environ.copy()
    set_current_locale(DEFAULT_LOCALE)
    yield
    set_current_locale(DEFAULT_LOCALE)
    for key in os.environ.keys() - environ.keys():
        del os.environ[key]
    for key, value in environ.items():
        if os.environ.get(key) != value:
            os.environ[key] = value


@pytest.fixture(autouse=True)
def _no_stragglers_from_the_previous_test():
    """上一条测试掉队的后台线程,不许写进这一条的账。

    `fresh_client()` 已经会在 drop_all 之前等它们收尾(见 tests/util 里那段说明),但那发生在
    **测试函数体里** —— 而多数测试是先 `monkeypatch.setattr(host, "run_turn", ...)`、后
    `fresh_client()`。上一条掉队的那一轮恰好在被等到的前一刻调用 `host.run_turn`,那时它已经
    指向本条测试打的桩了,于是本条测试凭空多记一轮。

    CI 上报出来是「跑起来的轮数不对(应为 12):13」,而多出来的那一轮根本不属于那条测试 ——
    本机复现不了(窗口太窄),把 drain 起下一轮的时机推后 0.25 秒就 100% 稳定复现。
    这类失败最难查的地方在于:红的那条测试是无辜的,肇事的是它前面那条。

    在测试函数体**之前**等,monkeypatch 就永远碰不到上一条的尾巴。没有掉队线程时三个 wait
    立刻返回,代价只是一次 threading.enumerate()。
    """
    from app.domain.agent.autopilot import wait_for_idle_autopilot
    from app.domain.agent.host import wait_for_idle_turns
    from app.domain.jobs import wait_for_idle_jobs

    wait_for_idle_turns()
    wait_for_idle_autopilot()
    wait_for_idle_jobs()
    yield
    # 有些测试把 jobs 里的 Thread 换成「start 什么都不做」的替身:派发器以为那个任务还在跑,名额永远
    # 不还 —— 漏满上限之后,**后面每一条测试**派发的任务都排队不动,表现是全量跑到一半整体卡住。
    # 每条测试之后换一个新的派发器;真在跑的线程照旧由上面那几个 wait 等着。
    from app.domain.jobs import reset_runner

    reset_runner()
    # 用例里经接口建的飞书机器人会真的起一个 worker 子进程和一条读它输出的泵线程。子进程拿假凭据连不上、
    # 自己退出后,泵还要写最后一次状态 —— 不在这里收掉的话,它会写进**下一条**用例刚清过的库,
    # CI 上报成那一条的「no such table: feishu_bots」(时红时绿,红的那条是无辜的)。
    from app.integrations.feishu.connections import stop_all_connections

    stop_all_connections()


@pytest.fixture(autouse=True)
def _reset_runtime_probes():
    """转写、克隆的「跑不跑得起来」和「正在下」都是**进程级**缓存,而它们探测的是真实机器
    (起子进程 import funasr / f5_tts)。不清的话,一个用例 monkeypatch 出来的结果会渗给下一个,
    表现是单独跑全绿、全量跑红 —— 三条路都清,而不是只清当时踩到的那一条。"""
    from app.ai.runtime import asr_models, f5_models, separation_models, tts_models

    def reset() -> None:
        asr_models.clear_runtime_probes()
        tts_models.clear_runtime_probes()
        #: 分离那条也是真探测(起子进程 import demucs.api),同样会跨用例渗漏。
        separation_models.clear_runtime_probes()
        for module in (asr_models, tts_models, f5_models):
            module._store.reset()
        for engine in separation_models.ENGINES:
            separation_models._store.clear(engine)

    reset()
    yield
    reset()


@pytest.fixture(autouse=True)
def _no_model_catalog_network():
    """**测试套不许去问真实的模型目录。**

    对话启动会顺手查一下端点的模型列表(拿上下文窗口)。测试里配的都是假地址,而这台机器
    走代理时,连不上的地址不会立刻被拒,要挂满 8 秒才超时 —— 恰好等于 `_wait_idle` 的 8 秒,
    于是两个 8 秒赛跑,谁先到看当时网络。表现出来就是 agent 那一批**概率性**变红:
    单独跑绿(目录被前一个用例缓存了),随机顺序跑红(缓存键对不上,真的出网)。
    倒下的那个还会连累后面几个——`fresh_client` 只等 5 秒就重建库,而线程还卡在网络上。

    进程级缓存也一并清掉:跨用例渗漏正是"单独跑全绿、全量跑红"的另一半原因。
    """
    from app.ai import model_catalog

    model_catalog.clear_cache()
    yield
    model_catalog.clear_cache()


@pytest.fixture(autouse=True)
def _catalog_returns_nothing(monkeypatch):
    """默认让目录查询直接返回空 —— 要测目录本身的用例自己 monkeypatch `httpx.get`
    (见 tests/test_model_catalog.py,它 stub 的是更底下那一层,不受这条影响)。"""
    from app.ai import model_catalog

    monkeypatch.setattr(model_catalog, "cached_model", lambda *a, **kw: None)


@pytest.fixture(autouse=True)
def _conversations_are_not_named_over_the_network(monkeypatch):
    """**测试套不替对话起名。**

    第一轮答完会另起一个线程,用这段对话的模型照聊的内容起名(domain/agent/titles)。测试里配的都是假地址,真去连
    就是出网、重试、退避,线程还活过测试本身 —— 和模型目录那条同一个道理(见 _no_model_catalog_network)。起不出名字
    本来就停在第一句话那个名字上,这里的默认就是那样。要测起名的用例自己 monkeypatch `titles._ask`。
    """
    from app.domain.agent import titles

    def unreachable(*_args, **_kwargs):
        raise RuntimeError("the test suite does not name conversations over the network")

    monkeypatch.setattr(titles, "_ask", unreachable)


@pytest.fixture(autouse=True)
def _background_work_ends_while_the_patches_are_still_on(monkeypatch):
    """这条测试派出去的后台活(智能体的一轮和它顺手起的「起名」线程、自动放行、in-process 任务),在测试的桩**还在**的时候收完。

    依赖 `monkeypatch`,所以它的收尾排在 monkeypatch 撤桩**之前**。此前只在下一条测试开头等(_no_stragglers_from_the_previous_test),
    那时桩已经撤了:答完第一轮才起的起名线程要是起步晚了一点(机器忙;tests/thread_jitter.py 能稳定复现),它拿到的是
    **真的** `titles._ask`,对着测试里配的假地址出网、重试、退避,在下一条测试里还活着。没有后台活就当场返回。
    """
    yield
    from app.domain.agent.autopilot import AUTOPILOT_THREAD_NAME
    from app.domain.agent.host import TURN_THREAD_NAME
    from app.domain.jobs import JOB_THREAD_NAME

    #: 只按线程名等**真在跑的**:不看派发器的账(有的测试把派发器的 Thread 换成「start 什么都不做」的替身,账上那一条永远
    #: 「在跑」),也不调用要读钟的等待函数 —— 这时测试的桩还在,有的测试把全局的 `time.monotonic` 换成了只走三下的假钟。
    #: 钟用 conftest 导入时拿到的那个真的。
    #: 每次重新数:一轮答完才起的起名线程也叫 TURN_THREAD_NAME,它在前一条线程结束之前就已经起来了。
    names = (TURN_THREAD_NAME, AUTOPILOT_THREAD_NAME, JOB_THREAD_NAME)
    deadline = _real_monotonic() + 30
    while _real_monotonic() < deadline:
        alive = [t for t in threading.enumerate() if t.name in names and t.is_alive()]
        if not alive:
            break
        alive[0].join(max(0.0, deadline - _real_monotonic()))


@pytest.fixture(autouse=True)
def _no_remote_size_network():
    """**测试套不许去问下载源的文件大小。**

    列模型卡片会顺手问一次"这些权重实际多大"(ai/runtime/remote_size)。缓存缺失时它在后台起线程
    去请求 —— 测试里那就是真的出网,慢、看网络脸色、而且线程会活过测试本身。
    和模型目录那条同一个道理(见 _no_model_catalog_network),这里一并挡掉:
    默认返回 None = "问不到",于是各处退回目录里那个估算值,正是没有网络时的真实行为。
    """
    from app.ai.runtime import remote_size

    remote_size.clear_cache()
    yield
    remote_size.clear_cache()


@pytest.fixture(autouse=True)
def _remote_size_says_unknown(monkeypatch):
    """要测 remote_size 自己的用例请打桩更底下那一层(httpx),不受这条影响。"""
    from app.ai.runtime import remote_size

    monkeypatch.setattr(remote_size, "cached_files", lambda *a, **kw: None)
    monkeypatch.setattr(remote_size, "files_for", lambda *a, **kw: None)


#: `docs/PROCESS_STATE.md` 第三节登记的那几处**启动时装配的配置快照**。
#:
#: 它们是进程级的可变状态,而测试之间没有人还原它们 —— 于是一条测试把
#: `/api/settings/ai-runtime` 的 `max_retries` PUT 成 6,后面**所有**会重试的测试都跟着
#: 退避六次。实测:同一条"连不上时目录为空"的测试单独跑 4.68 秒,跟在 test_http_retry 后面
#: 跑 26.37 秒(5.6 倍),全量里涨到 49.5 秒 —— 因为还有别处把它推到了 9。
#:
#: **测试全绿,只是慢;而"慢"在三千多个点里是看不见的。**
#:
#: 体系做到了"把进程级状态写下来"(PROCESS_STATE.md + test_process_state_inventory 强制
#: 清单完整),但没做到"测试之间把它还原" —— **登记本身制造了一种已受控的错觉**。
_SNAPSHOT_STATE = (
    ("app.core.http_retry", "_max_retries"),
    ("app.core.outbound_guard", "_allowlist"),
    ("app.ai.runtime.config", "_cached"),
    ("app.ai.runtime.config", "_source"),
)


@pytest.fixture(autouse=True)
def _restore_process_snapshots(request):
    """每条测试跑完把那几处配置快照还原成它进来时的样子。

    还原的是**进来时**的值而不是模块默认值:有的测试会在 fixture 里故意设好一个值,
    按默认值还原等于把那条测试自己的布置也抹掉。

    **先等这条测试起的后台线程走完,再还原。** 反过来的话,还原之后才跑到的那条线程会把它看到的配置重新缓存进去,
    而下一条测试「进来时的值」就是这份 —— 从此一路传下去。实测:`GET /api/settings/tts` 顺手起的运行时探测线程
    (起步晚一点,tests/thread_jitter.py)在还原之后读配置,把上一条测试库里的 fish-speech 缓存进 `_cached`,
    隔了五条的 test_tts_config_get_and_update 读到的默认引擎就成了 fish-speech。
    """
    import importlib

    saved = []
    for module_name, attribute in _SNAPSHOT_STATE:
        try:
            module = importlib.import_module(module_name)
        except ImportError:  # pragma: no cover —— 模块搬家时不该让整套测试炸掉
            continue
        saved.append((module, attribute, getattr(module, attribute, None)))
    yield
    _let_the_body_threads_finish(request.node)
    for module, attribute, value in saved:
        setattr(module, attribute, value)
