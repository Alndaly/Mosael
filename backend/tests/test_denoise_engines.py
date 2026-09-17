"""降噪的两个开源模型引擎:RNNoise(打包的模型 + ffmpeg)与 DeepFilterNet(下载的二进制)。

钉住的是:

1. 打进安装包的 RNNoise 模型就是核对过的那一份,打包命令带上了它;
2. DeepFilterNet 的下载**按哈希校验**,对不上就不装、不留半截文件;没有发布文件的平台直说;
3. 适配器把档位落到对的参数上、补上延迟、把产物放到约定的位置;
4. 每个引擎说得出自己的名字、适用场合、没准备好时去哪儿准备 —— 界面不认识引擎,全靠这几句。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from app.ai.providers.contracts.denoise import DenoiseError, DenoiseRequest

ROOT = Path(__file__).resolve().parents[1]


class TestRNNoise模型:
    def test_打包的模型就是核对过的那一份(self) -> None:
        from app.ai.providers.adapters.local import rnnoise_denoise as rn

        model = rn.MODEL_DIR / rn.MODEL_FILE
        assert hashlib.sha256(model.read_bytes()).hexdigest() == rn.MODEL_SHA256
        assert rn.MODEL_SHA256 in (rn.MODEL_DIR / "README.md").read_text(encoding="utf-8")

    def test_打包命令带上了模型文件(self) -> None:
        """漏了这一条,开发机上一切正常,装出来的应用里 RNNoise 永远"没准备好"。"""
        command = json.loads((ROOT.parent / "package.json").read_text(encoding="utf-8"))["scripts"]["build:backend"]
        assert "--add-data app/ai/runtime/models/rnnoise/somnolent-hogwash.rnnn:app/ai/runtime/models/rnnoise" in command

    @pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")
    def test_真的在降噪(self, tmp_path) -> None:
        from app.ai.providers.adapters.local.ffmpeg_denoise import measure_levels
        from app.ai.providers.adapters.local.rnnoise_denoise import RnnoiseDenoiseAdapter

        adapter = RnnoiseDenoiseAdapter()
        if not adapter.runtime_ready():
            pytest.skip("这台机器的 ffmpeg 不带 arnndn")
        #: 一阵一阵的噪声,中间没有说话 —— 语音模型该把它几乎全压掉。
        noise = tmp_path / "bursts.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
             "anoisesrc=d=4:c=white:a=0.08:r=48000,volume='if(lt(mod(t*7,1),0.15),1,0.05)':eval=frame",
             str(noise)],
            check=True,
        )
        _, before = measure_levels(noise)
        levels = {}
        for strength in ("light", "strong"):
            out = adapter.denoise(DenoiseRequest(noise, strength), tmp_path / f"{strength}.wav")
            levels[strength] = measure_levels(out)[1]
        assert levels["strong"] < before - 15
        assert levels["strong"] < levels["light"] < before


def _fake_download(content: bytes):
    def download(url: str, target: Path, **kwargs) -> str:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return "application/octet-stream"

    return download


class TestDeepFilterNet安装:
    @pytest.fixture
    def runtime(self, monkeypatch, tmp_path):
        from app.ai.runtime import denoise_models as dm

        monkeypatch.setattr(dm, "MANAGED_DENOISE_ROOT", tmp_path / "denoise")
        dm.deepfilter_ready.cache_clear()
        yield dm
        dm.deepfilter_ready.cache_clear()

    def _pretend_platform(self, monkeypatch, dm, content: bytes) -> None:
        spec = dm._Binary("deep-filter-test", hashlib.sha256(content).hexdigest(), len(content))
        monkeypatch.setattr(dm, "deepfilter_binary_spec", lambda: spec)

    def test_哈希对得上才装__装完就绪(self, monkeypatch, runtime) -> None:
        from app.ai.providers import media_transfer

        content = b"#!/bin/sh\necho ok\n"
        self._pretend_platform(monkeypatch, runtime, content)
        monkeypatch.setattr(media_transfer, "download_to_path", _fake_download(content))

        installed = runtime._install_deepfilter()
        assert installed == runtime.deepfilter_path() and installed.read_bytes() == content
        assert runtime.deepfilter_ready()
        if sys.platform != "win32":
            assert installed.stat().st_mode & stat.S_IXUSR, "要能执行"

    def test_哈希对不上就拒装__不留半截文件(self, monkeypatch, runtime) -> None:
        """发布页上的文件被换掉时,宁可装不上,也不去运行一个没见过的东西。"""
        from app.ai.providers import media_transfer

        self._pretend_platform(monkeypatch, runtime, b"the real one")
        monkeypatch.setattr(media_transfer, "download_to_path", _fake_download(b"something else"))

        with pytest.raises(RuntimeError, match="校验不符"):
            runtime._install_deepfilter()
        assert not runtime.deepfilter_ready()
        assert list(runtime.MANAGED_DENOISE_ROOT.iterdir()) == [], "校验失败的文件要删掉"

    def test_装失败_原因留在状态里(self, monkeypatch, runtime) -> None:
        from app.ai.providers import media_transfer

        self._pretend_platform(monkeypatch, runtime, b"the real one")
        monkeypatch.setattr(media_transfer, "download_to_path", _fake_download(b"tampered"))
        runtime._run_install(runtime.DEEPFILTER)
        status = runtime.install_status(runtime.DEEPFILTER)
        assert status["status"] == "failed" and "校验不符" in status["message"]
        runtime._store.clear(runtime.DEEPFILTER)

    def test_没有发布文件的平台直说(self, monkeypatch, runtime) -> None:
        monkeypatch.setattr(runtime, "deepfilter_binary_spec", lambda: None)
        assert runtime.install_status(runtime.DEEPFILTER)["status"] == "unsupported"
        with pytest.raises(RuntimeError, match="这个平台"):
            runtime.start_install(runtime.DEEPFILTER)

    def test_只有要装的引擎能装(self, runtime) -> None:
        with pytest.raises(KeyError):
            runtime.start_install("ffmpeg")

    def test_四个平台都有核对过的哈希(self) -> None:
        from app.ai.runtime.denoise_models import _DEEPFILTER_BINARIES

        assert set(_DEEPFILTER_BINARIES) == {("darwin", "arm64"), ("darwin", "x86_64"), ("win32", "amd64"), ("linux", "x86_64")}
        for spec in _DEEPFILTER_BINARIES.values():
            assert len(spec.sha256) == 64 and spec.size > 20_000_000


@pytest.mark.skipif(sys.platform == "win32", reason="用一个 sh 脚本冒充二进制")
class TestDeepFilterNet适配器:
    def _fake_binary(self, tmp_path: Path) -> tuple[Path, Path]:
        """冒充 deep-filter:记下参数,把输入原样写到 --output-dir 里同名文件。"""
        log = tmp_path / "args.txt"
        script = tmp_path / "deep-filter"
        script.write_text(
            "#!/bin/sh\n"
            f'echo "$@" > "{log}"\n'
            'out=""; prev=""\n'
            'for a in "$@"; do if [ "$prev" = "--output-dir" ]; then out="$a"; fi; prev="$a"; last="$a"; done\n'
            'cp "$last" "$out/$(basename "$last")"\n'
        )
        script.chmod(0o755)
        return script, log

    @pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")
    @pytest.mark.parametrize(("strength", "limit"), [("light", "12"), ("medium", "24"), ("strong", "100")])
    def test_档位落到衰减上限__补上延迟(self, monkeypatch, tmp_path, strength, limit) -> None:
        from app.ai.providers.adapters.local.deepfilter_denoise import DeepFilterDenoiseAdapter
        from app.ai.runtime import denoise_models as dm

        binary, log = self._fake_binary(tmp_path)
        monkeypatch.setattr(dm, "deepfilter_path", lambda: binary)
        source = tmp_path / "in.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=d=1:sample_rate=44100", str(source)], check=True)

        out = DeepFilterDenoiseAdapter().denoise(DenoiseRequest(source, strength), tmp_path / "result" / "clean.wav")
        args = log.read_text().split()
        assert args[args.index("--atten-lim-db") + 1] == limit
        assert "--compensate-delay" in args, "不补延迟,放回视频就对不上口型"
        assert out.is_file()
        rate = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=sample_rate", "-of", "csv=p=0", str(out)],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert rate == "48000", "交给模型前要转成它的原生采样率"
        assert not (tmp_path / "result" / "clean-deepfilter").exists(), "中间目录要清掉"

    def test_没装时说清去哪装(self, monkeypatch, tmp_path) -> None:
        from app.ai.providers import registry
        from app.ai.runtime import denoise_models as dm
        from app.domain.denoise import ready_adapter

        monkeypatch.setattr(dm, "deepfilter_path", lambda: tmp_path / "nothing")
        dm.deepfilter_ready.cache_clear()
        try:
            assert not registry.DENOISE_ADAPTERS["deepfilternet"].runtime_ready()
            with pytest.raises(DenoiseError, match="设置"):
                ready_adapter("deepfilternet")
        finally:
            dm.deepfilter_ready.cache_clear()


class Test引擎自己说得清自己:
    def test_每个引擎的名字_说明_准备提示都有中英文(self) -> None:
        """界面不认识任何引擎,这几句话全靠引擎自己给。加一个引擎忘了写,界面上就是一串 key。"""
        from app.ai.providers.registry import DENOISE_ADAPTERS
        from app.core.i18n import t

        for adapter in DENOISE_ADAPTERS.values():
            keys = [adapter.label_key, adapter.description_key]
            if adapter.setup_hint_key:
                keys.append(adapter.setup_hint_key)
            for key in keys:
                for locale in ("zh", "en"):
                    assert t(key, locale) != key, f"{adapter.engine_id} 缺文案:{key} ({locale})"

    def test_说明里讲清会不会去掉音乐(self) -> None:
        from app.ai.providers.registry import DENOISE_ADAPTERS
        from app.core.i18n import t

        for adapter in DENOISE_ADAPTERS.values():
            assert "音乐" in t(adapter.description_key, "zh"), adapter.engine_id

    def test_清单带着安装状态(self, monkeypatch, tmp_path) -> None:
        from app.ai.runtime import denoise_models as dm
        from app.domain.denoise import list_engines

        monkeypatch.setattr(dm, "deepfilter_path", lambda: tmp_path / "nothing")
        dm.deepfilter_ready.cache_clear()
        try:
            rows = {row["engine"]: row for row in list_engines()}
        finally:
            dm.deepfilter_ready.cache_clear()
        assert list(rows)[0] == "ffmpeg"
        assert rows["ffmpeg"]["installable"] is False and rows["ffmpeg"]["status"] == "ready"
        df = rows["deepfilternet"]
        assert df["installable"] is True and df["ready"] is False
        assert df["setup_hint"] == "denoiseSetup_deepfilternet"
        assert df["status"] in {"missing", "unsupported"}
