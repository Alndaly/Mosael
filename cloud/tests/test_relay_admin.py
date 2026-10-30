"""官方中转的运维命令:从零开通一个能用的网关 —— 生成钥匙、建套餐、开通、建模型、定价、加通道;上游 Key 不出现在任何输出里。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from cloud.cli import main
from cloud.db import Database
from cloud.domain import catalog
from cloud.models import CloudUpstreamProvider, CloudUser, now
from cloud.schema import upgrade_database

UPSTREAM_KEY = "sk-live-do-not-print-0123"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUD_DATA_DIR", str(tmp_path))
    for name in ("CLOUD_DATABASE_URL", "CLOUD_CHANNEL_KEY", "CLOUD_UPSTREAM_KEY", "CLOUD_OFFICIAL_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    url = f"sqlite:///{tmp_path / 'cloud.db'}"
    upgrade_database(url)
    database = Database(url)
    with database.session() as db:
        db.add(CloudUser(email="alice@example.com"))
        db.commit()
    yield database
    database.dispose()


def run(capsys, *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_open_a_working_relay_from_scratch(env, capsys, monkeypatch):
    code, key, _ = run(capsys, "channel-key")
    assert code == 0
    monkeypatch.setenv("CLOUD_CHANNEL_KEY", key.strip())

    assert run(capsys, "plan-set", "--slug", "pro", "--name", "Pro", "--period", "year",
               "--monthly-credits", "20000", "--credit-ttl-days", "60")[0] == 0
    code, out, _ = run(capsys, "subscribe", "--email", "Alice@Example.com", "--plan", "pro")
    assert code == 0 and "当前积分 20000" in out

    assert run(capsys, "model-set", "--id", "deepseek-chat", "--label", "DeepSeek V3", "--max-output-tokens", "8000")[0] == 0
    assert run(capsys, "price-set", "--model", "deepseek-chat", "--input-per-1k", "2", "--output-per-1k", "8")[0] == 0
    monkeypatch.setenv("CLOUD_UPSTREAM_KEY", UPSTREAM_KEY)
    code, out, _ = run(capsys, "provider-add", "--name", "DeepSeek", "--base-url", "https://api.deepseek.com/v1")
    assert code == 0 and UPSTREAM_KEY not in out
    with env.session() as db:
        provider_id = db.scalar(select(CloudUpstreamProvider)).id

    code, out, _ = run(capsys, "channel-add", "--model", "deepseek-chat", "--provider", provider_id,
                       "--upstream-model", "deepseek-chat", "--priority", "0")
    assert code == 0 and UPSTREAM_KEY not in out

    code, listing, _ = run(capsys, "channel-list")
    assert "deepseek-chat" in listing and UPSTREAM_KEY not in listing

    with env.session() as db:
        stored = db.scalar(select(CloudUpstreamProvider))
        assert UPSTREAM_KEY not in stored.api_key_encrypted
        #: 网关此刻就能列出它。
        assert [one.model.id for one in catalog.listed_models(db, at=now() + timedelta(seconds=1))] == ["deepseek-chat"]

    code, out, _ = run(capsys, "balance", "--email", "alice@example.com")
    assert "20000 积分" in out and "Pro" in out


def test_a_provider_is_refused_without_a_channel_key(env, capsys, monkeypatch):
    monkeypatch.setenv("CLOUD_UPSTREAM_KEY", UPSTREAM_KEY)
    code, _, err = run(capsys, "provider-add", "--name", "x", "--base-url", "https://x.example/v1")
    assert code == 2 and "CLOUD_CHANNEL_KEY" in err
    with env.session() as db:
        assert db.scalar(select(CloudUpstreamProvider)) is None


def test_unknown_account_or_plan_is_a_clear_refusal(env, capsys):
    code, _, err = run(capsys, "subscribe", "--email", "nobody@example.com", "--plan", "pro")
    assert code == 2 and "没有这个套餐" in err
    run(capsys, "plan-set", "--slug", "pro", "--name", "Pro", "--period", "month",
        "--monthly-credits", "10", "--credit-ttl-days", "30")
    code, _, err = run(capsys, "subscribe", "--email", "nobody@example.com", "--plan", "pro")
    assert code == 2 and "没有这个账号" in err


def test_a_plan_can_be_priced_for_online_purchase(env, capsys):
    code, out, _ = run(capsys, "plan-set", "--slug", "pro", "--name", "Pro", "--period", "month",
                       "--monthly-credits", "1000", "--credit-ttl-days", "60", "--price", "29.9")
    assert code == 0 and "¥29.90" in out
    with env.session() as db:
        from cloud.models import CloudPlan

        assert db.scalar(select(CloudPlan)).price_cents == 2990
    code, _, err = run(capsys, "plan-set", "--slug", "pro", "--name", "Pro", "--period", "month",
                       "--monthly-credits", "1000", "--credit-ttl-days", "60", "--price", "abc")
    assert code == 2 and "--price" in err
