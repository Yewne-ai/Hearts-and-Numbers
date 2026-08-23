"""mode 接入主链路的行为——2026-08-09。

重点不是"判得准不准"（那要真模型），是**接进去之后没把原来的链路弄坏**：

- 开关关闭时，一切和接入前逐字节一致：不多调一次分类、prompt 不加块
- 分类器抛异常时，退回无 mode 的老行为，不能把主链路拖垮
- v2 判 crisis 时走 safety 那条固定文案，不进 LLM
- concern 相反：进 LLM，带 concern 块
"""

import json

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


class _SpyProvider:
    """记下每次生成拿到的 mode。两个方法都要有——流式路径优先走 stream_complete，
    只有 AttributeError 才降级到 complete，只测一个会漏掉另一个。
    """

    def __init__(self) -> None:
        self.complete_modes: list[ResponseMode | None] = []
        self.stream_modes: list[ResponseMode | None] = []

    async def complete(
        self, user_text, history=None, persona="nini", mode=None, chat_mode=None
    ):
        self.complete_modes.append(mode)
        return "好的。"

    async def stream_complete(
        self, user_text, history=None, persona="nini", mode=None, chat_mode=None
    ):
        self.stream_modes.append(mode)
        for token in ("好", "的", "。"):
            yield token


class TestStreamPathGetsMode:
    """流式那条路也必须把 mode 传下去——**前端只走流式**。

    2026-08-12 线上实测踩到：`stream_complete()` 漏传 mode，导致分类照跑照计费，
    块却一个都没生效。非流式接口是对的，所以只测 /v1/chat/demo 看不出来。
    这几条就是为了钉住"两条路都要过"。
    """

    def _run(self, monkeypatch: pytest.MonkeyPatch, mode: ResponseMode) -> _SpyProvider:
        spy = _SpyProvider()
        _install(monkeypatch, _StubClassifier(mode))
        monkeypatch.setattr(settings, "response_mode_enabled", True)
        monkeypatch.setattr(
            "app.api.v1.chat.get_llm_provider", lambda: (spy, False)
        )
        resp = client.post(
            "/v1/chat/demo/stream", json={"user_text": "今天被我妈说了一顿"}
        )
        assert resp.status_code == 200, resp.text
        self.body = resp.text
        return spy

    def test_stream_complete_receives_mode(self, monkeypatch: pytest.MonkeyPatch):
        spy = self._run(monkeypatch, ResponseMode.VENT)
        assert spy.stream_modes == [ResponseMode.VENT]

    def test_stream_done_event_carries_mode_and_care(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """前端拿不到 care 就永远显示不了现实求助入口——文档 8.5.2 的底线在这里断掉。"""
        self._run(monkeypatch, ResponseMode.CONCERN)
        done = [
            json.loads(line[6:])
            for line in self.body.splitlines()
            if line.startswith("data: ") and '"type": "done"' in line
        ]
        assert len(done) == 1
        assert done[0]["mode"] == "concern"
        # concern → S2 → 安静地摆着，不打断
        assert done[0]["care"]["level"] == "quiet"
        assert done[0]["care"]["hotlines"]

    def test_stream_degraded_fallback_also_receives_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """provider 不支持流式时降级到 complete()，那条路同样不能把 mode 丢了。

        这个 spy **必须真的没有 stream_complete 这个属性**（像 MockProvider 那样），
        不能用 `del spy.stream_complete`（方法在类上，实例删不掉）也不能置成 None
        （调用 None 抛的是 TypeError，而服务层只接 AttributeError，降级根本不会触发）。
        """

        class _NoStreamSpy:
            def __init__(self) -> None:
                self.complete_modes: list[ResponseMode | None] = []

            async def complete(
                self,
                user_text,
                history=None,
                persona="nini",
                mode=None,
                chat_mode=None,
            ):
                self.complete_modes.append(mode)
                return "好的。"

        spy = _NoStreamSpy()
        _install(monkeypatch, _StubClassifier(ResponseMode.ADVICE))
        monkeypatch.setattr(settings, "response_mode_enabled", True)
        monkeypatch.setattr("app.api.v1.chat.get_llm_provider", lambda: (spy, False))

        resp = client.post("/v1/chat/demo/stream", json={"user_text": "我该怎么办"})
        assert resp.status_code == 200, resp.text
        assert spy.complete_modes == [ResponseMode.ADVICE]


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
