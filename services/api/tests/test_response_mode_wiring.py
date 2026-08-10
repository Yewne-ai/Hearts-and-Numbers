"""mode 接入主链路的行为——2026-08-09。

重点不是"判得准不准"（那要真模型），是**接进去之后没把原来的链路弄坏**：

- 开关关闭时，一切和接入前逐字节一致：不多调一次分类、prompt 不加块
- 分类器抛异常时，退回无 mode 的老行为，不能把主链路拖垮
- v2 判 crisis 时走 safety 那条固定文案，不进 LLM
- concern 相反：进 LLM，带 concern 块
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.domain.conversation import service as conv_service
from app.domain.conversation.modes import ResponseMode
from app.llm.deepseek import _system_prompt_with_mode
from app.main import app

client = TestClient(app)


class _StubClassifier:
    def __init__(self, mode: ResponseMode | Exception) -> None:
        self._mode = mode
        self.calls = 0

    async def classify(self, user_text: str) -> ResponseMode:
        self.calls += 1
        if isinstance(self._mode, Exception):
            raise self._mode
        return self._mode


@pytest.fixture(autouse=True)
def _force_mock_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_provider", "mock")


def _install(monkeypatch: pytest.MonkeyPatch, stub: _StubClassifier) -> None:
    monkeypatch.setattr(conv_service, "get_response_mode_classifier", lambda: stub)


class TestSwitchOff:
    """默认关。关着的时候这条链路必须和接入前完全一样。"""

    def test_disabled_by_default(self):
        """断言**代码里的默认值**，不是加载后的值——后者会被本地 .env 覆盖，
        而这条要守的是"没人显式打开时，生产不受影响"。
        """
        default = type(settings).model_fields["response_mode_enabled"].default
        assert default is False

    @pytest.mark.asyncio
    async def test_disabled_skips_classification_entirely(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """关着时连分类器都不该实例化——否则就是白花一次调用，
        正是 2026-08-03 删掉 scene 的原因，不能再犯一次。"""
        stub = _StubClassifier(ResponseMode.VENT)
        _install(monkeypatch, stub)
        monkeypatch.setattr(settings, "response_mode_enabled", False)

        mode = await conv_service._classify_mode_safe("我今天很累", "req-1")
        assert mode is None
        assert stub.calls == 0

    def test_disabled_response_has_empty_mode(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "response_mode_enabled", False)
        resp = client.post("/v1/chat/demo", json={"user_text": "今天有点累"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["mode"] == ""


class TestFailureIsolation:
    """分类是增强，不是依赖。它坏了只能让效果回到接入前，不能让请求失败。"""

    @pytest.mark.asyncio
    async def test_classifier_exception_falls_back_to_none(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        _install(monkeypatch, _StubClassifier(RuntimeError("boom")))
        monkeypatch.setattr(settings, "response_mode_enabled", True)

        assert await conv_service._classify_mode_safe("我今天很累", "req-2") is None

    def test_classifier_exception_still_returns_200(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        _install(monkeypatch, _StubClassifier(RuntimeError("boom")))
        monkeypatch.setattr(settings, "response_mode_enabled", True)
        resp = client.post("/v1/chat/demo", json={"user_text": "今天有点累"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["reply"]


class TestCrisisRouting:
    """crisis 走固定文案，concern 走 LLM——两级的分野就在这里。"""

    def test_crisis_returns_fixed_text_without_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        _install(monkeypatch, _StubClassifier(ResponseMode.CRISIS))
        monkeypatch.setattr(settings, "response_mode_enabled", True)

        resp = client.post("/v1/chat/demo", json={"user_text": "我已经想好了"})
        body = resp.json()
        assert resp.status_code == 200, resp.text
        assert body["safety_flag"] == "crisis_keyword"
        # 固定文案的特征：给出援助热线，且不提医疗措辞
        assert "400-161-9995" in body["reply"]
        for medical in ("医生", "治疗", "诊断"):
            assert medical not in body["reply"]

    def test_concern_goes_through_llm(self, monkeypatch: pytest.MonkeyPatch):
        """concern 是"没明说"，硬停会把人推走——必须让模型说话。"""
        _install(monkeypatch, _StubClassifier(ResponseMode.CONCERN))
        monkeypatch.setattr(settings, "response_mode_enabled", True)

        body = client.post("/v1/chat/demo", json={"user_text": "天台的风好大啊"}).json()
        assert body["safety_flag"] == "ok"
        assert body["mode"] == "concern"
        assert "400-161-9995" not in body["reply"]


class TestPromptComposition:
    """块必须拼在人格后面，且 mode 为 None 时逐字节等于原来的人格 prompt。"""

    def test_none_mode_is_byte_identical_to_persona(self):
        from app.llm.deepseek import _system_prompt_for

        for persona in ("nini", "youyou"):
            assert _system_prompt_with_mode(persona, None) == _system_prompt_for(
                persona
            )

    @pytest.mark.parametrize("mode", list(ResponseMode))
    def test_block_is_appended_after_persona(self, mode: ResponseMode):
        from app.llm.deepseek import _system_prompt_for

        base = _system_prompt_for("nini")
        composed = _system_prompt_with_mode("nini", mode)
        assert composed.startswith(base)
        assert len(composed) > len(base)
