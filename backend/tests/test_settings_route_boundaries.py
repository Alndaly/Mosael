"""设置 API 只是统一 URL 前缀，不是一个能吞下所有设置领域的模块。"""

from __future__ import annotations

from pathlib import Path

RATCHET = True

ROUTES = Path(__file__).resolve().parents[1] / "app" / "api" / "routes"
SETTINGS = ROUTES / "settings"


def test_settings_routes_are_owned_by_domain_modules() -> None:
    expected = {
        "provider_profiles.py",
        "provider_oauth.py",
        "provider_models.py",
        "provider_defaults.py",
        "provider_pricing.py",
        "system.py",
    }

    assert not (ROUTES / "settings.py").exists(), "settings.py 又变成了跨领域路由总管"
    assert expected <= {path.name for path in SETTINGS.glob("*.py")}


def test_settings_router_only_composes_subrouters() -> None:
    source = (SETTINGS / "__init__.py").read_text(encoding="utf-8")

    assert "include_router" in source
    assert "@router." not in source, "聚合器不应重新拥有业务端点"
    assert len(source.splitlines()) <= 40, "聚合器开始积累业务逻辑"


def test_no_settings_route_domain_regrows_into_a_monolith() -> None:
    offenders = {
        path.name: len(path.read_text(encoding="utf-8").splitlines())
        for path in SETTINGS.glob("*.py")
        if path.name != "__init__.py" and len(path.read_text(encoding="utf-8").splitlines()) > 650
    }

    assert offenders == {}, f"设置路由再次跨越多个所有权边界:{offenders}"
