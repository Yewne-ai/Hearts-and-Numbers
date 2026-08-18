"""[2026-08-03] 人格 prompt 的解析链路 + admin 接口的安全默认值。

这套东西(admin.py / runtime_config.py / defaults.py)在此之前**只存在于线上服务器**，
仓库里没有，所以从来没被测过，Ronnie 和 Jesse 也看不到线上真实的人格设定。
这次收进 Git，补上测试锁住两件最容易出事的行为：

1. overrides 覆盖 defaults 的优先级——搞反了会让产品在后台的改动全部失效。
2. admin_token 没配时必须 503——搞错了等于把改 prompt 的接口对全网开放。
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.llm import runtime_config
from app.llm.defaults import DEFAULT_PERSONAS, PERSONA_KEYS
from app.main import app


@pytest.fixture(autouse=True)
def _reset_cache():
    """runtime_config 按 mtime 缓存，测试间要清掉，否则互相串。"""
    runtime_config._cache = None
    runtime_config._cache_mtime = None
    yield
    runtime_config._cache = None
    runtime_config._cache_mtime = None


# ── 出厂默认 ────────────────────────────────────────────────────────────


def test_yewne_is_the_live_persona() -> None:
    """[2026-08-11] 合并成单一人格 yewne。

    youyou / nini 仍在 PERSONA_KEYS 里，**只为不让老客户端吃 422**，
    而且老会话重放 Aftercare 时还要用到——不是还支持多人格。
    真正生效的只有 yewne，见 runtime_config.resolve_persona。
    """
    assert "yewne" in PERSONA_KEYS
    assert set(PERSONA_KEYS) == {"yewne", "youyou", "nini"}


def test_every_persona_value_resolves_to_yewne() -> None:
    """客户端传什么都用 yewne。漏掉解析的地方会静默退回旧人格
    （TTS 音色、Aftercare 文案都有 .get 兜底），界面上看不出来。"""
    from app.llm.runtime_config import resolve_persona

    for value in ("nini", "youyou", "yewne", "", None):
        assert resolve_persona(value) == "yewne"


def test_default_personas_are_non_empty() -> None:
    for key in PERSONA_KEYS:
        assert DEFAULT_PERSONAS[key].strip(), f"{key} 的出厂 prompt 不能为空"


def test_unknown_persona_falls_back_to_nini() -> None:
    """默认人格是妮妮；传了没见过的 key 不能抛异常，聊天要继续。"""
    assert runtime_config.get_persona("does-not-exist") == runtime_config.get_persona("nini")


# ── overrides 覆盖 defaults ─────────────────────────────────────────────


def test_overrides_win_over_defaults(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """核心优先级：后台改过的 prompt 必须盖住出厂值。搞反了产品的改动全部失效。"""
    path = tmp_path / "runtime_overrides.json"
    path.write_text(
        json.dumps({"personas": {"youyou": "后台改过的优优"}, "params": {"max_tokens": 999}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_config, "_OVERRIDES_PATH", path)

    assert runtime_config.get_persona("youyou") == "后台改过的优优"
    assert runtime_config.get_params()["max_tokens"] == 999
    # 没被覆盖的人格仍取出厂值
    assert runtime_config.get_persona("nini") == DEFAULT_PERSONAS["nini"]


def test_blank_override_does_not_wipe_a_persona(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """后台误存了空字符串时要退回出厂值，不能让人格变成空 prompt。"""
    path = tmp_path / "runtime_overrides.json"
    path.write_text(json.dumps({"personas": {"nini": "   "}}), encoding="utf-8")
    monkeypatch.setattr(runtime_config, "_OVERRIDES_PATH", path)

    assert runtime_config.get_persona("nini") == DEFAULT_PERSONAS["nini"]


def test_unknown_persona_key_in_overrides_is_ignored(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """overrides 里出现废弃的 key(比如改名前的 iris)不该被塞进有效人格表。"""
    path = tmp_path / "runtime_overrides.json"
    path.write_text(json.dumps({"personas": {"iris": "旧人格"}}), encoding="utf-8")
    monkeypatch.setattr(runtime_config, "_OVERRIDES_PATH", path)

    assert "iris" not in runtime_config.get_config()["personas"]


def test_missing_overrides_file_falls_back_to_defaults(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """本地开发没有这个文件，必须能正常跑。"""
    monkeypatch.setattr(runtime_config, "_OVERRIDES_PATH", tmp_path / "nope.json")

    assert runtime_config.get_persona("youyou") == DEFAULT_PERSONAS["youyou"]


# ── admin 接口的安全默认值 ──────────────────────────────────────────────


def test_admin_disabled_when_token_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """admin_token 留空时所有 admin 接口 503。

    这是 fail-safe：忘了配 token 的后果是"功能用不了"，而不是"谁都能改人格 prompt"。
    """
    monkeypatch.setattr(settings, "admin_token", "")
    client = TestClient(app)

    assert client.get("/v1/admin/llm-config").status_code == 503
    assert client.get("/v1/admin/llm-config", headers={"X-Admin-Token": "x"}).status_code == 503


def test_admin_rejects_wrong_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_token", "the-real-token")
    client = TestClient(app)

    assert client.get("/v1/admin/llm-config").status_code == 401
    assert (
        client.get("/v1/admin/llm-config", headers={"X-Admin-Token": "wrong"}).status_code
        == 401
    )


def test_admin_accepts_correct_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_token", "the-real-token")
    client = TestClient(app)

    response = client.get(
        "/v1/admin/llm-config", headers={"X-Admin-Token": "the-real-token"}
    )

    assert response.status_code == 200
    assert set(response.json()["personas"]) == {"yewne", "youyou", "nini"}
