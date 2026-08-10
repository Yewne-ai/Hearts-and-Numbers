"""会话级安全锁——对齐产品文档 8.4 / 8.6。

文档 8.4 对 S3 的要求是「停止普通陪伴」，8.6 状态机的终点是「结束普通 AI 服务」。
**逐轮无状态做不到这件事**——用户下一句说别的就又回到正常聊天了，那次识别白做。

这套测试守的就是"下一轮说别的也不放行"。不打网络，持久化用 stub。
"""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.domain.conversation import service as conv_service
from app.domain.conversation.modes import ResponseMode
from app.main import app

client = TestClient(app)
CID = uuid4()


class _StubClassifier:
    def __init__(self, mode: ResponseMode) -> None:
        self._mode = mode
        self.calls = 0

    async def classify(self, user_text: str) -> ResponseMode:
        self.calls += 1
        return self._mode


class _StubPersistence:
    """只实现锁相关的三个方法，其余按最小可用给。"""

    def __init__(self, locked: bool = False, read_raises: bool = False) -> None:
        self.locked = locked
        self.read_raises = read_raises
        self.lock_calls: list[tuple[UUID, str]] = []

    async def save_exchange(self, **kw) -> UUID:
        return kw.get("conversation_id") or CID

    async def is_safety_locked(self, *, external_user_id, conversation_id) -> bool:
        if self.read_raises:
            raise RuntimeError("db down")
        return self.locked

    async def lock_for_safety(
        self, *, external_user_id, conversation_id, risk_level
    ) -> None:
        self.lock_calls.append((conversation_id, risk_level))


@pytest.fixture(autouse=True)
def _mock_provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "response_mode_enabled", True)


def _install(monkeypatch: pytest.MonkeyPatch, stub: _StubClassifier) -> None:
    monkeypatch.setattr(conv_service, "get_response_mode_classifier", lambda: stub)


class TestLockedSessionShortCircuits:
    @pytest.mark.asyncio
    async def test_locked_session_skips_classification_entirely(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """已锁的会话不该再花一次分类调用——那是纯浪费，
        而且无论这轮说什么都走同一条固定文案。"""
        from app.domain.conversation.schemas import ChatDemoRequest, Persona

        stub = _StubClassifier(ResponseMode.VENT)
        _install(monkeypatch, stub)
        req = ChatDemoRequest(
            user_text="对了你喜欢吃什么",
            external_user_id="u1",
            conversation_id=CID,
            persona=Persona.NINI,
        )
        assert (
            await conv_service._safety_locked(_StubPersistence(locked=True), req, "r1")
            is True
        )
        assert stub.calls == 0

    @pytest.mark.asyncio
    async def test_first_turn_is_never_locked(self):
        """首轮没有 conversation_id，不可能锁着。"""
        from app.domain.conversation.schemas import ChatDemoRequest

        req = ChatDemoRequest(user_text="在吗", external_user_id="u1")
        assert (
            await conv_service._safety_locked(_StubPersistence(locked=True), req, "r1")
            is False
        )


class TestDegradesSafely:
    """锁读不到时必须**放行**，不能反过来。"""

    @pytest.mark.asyncio
    async def test_no_persistence_means_not_locked(self):
        """没开持久化 → 退回接入前的逐轮行为。没有会话状态就锁不住，
        硬装作锁住了反而会骗人。"""
        from app.domain.conversation.schemas import ChatDemoRequest

        req = ChatDemoRequest(
            user_text="随便说说", external_user_id="u1", conversation_id=CID
        )
        assert await conv_service._safety_locked(None, req, "r1") is False

    @pytest.mark.asyncio
    async def test_read_failure_does_not_lock_everyone_out(self):
        """数据库抖动不能把正常会话锁住——那会让所有人都收到危机文案。
        反方向的风险（漏一次锁）由这一轮的分类器兜底：真危机会被重新识别。
        """
        from app.domain.conversation.schemas import ChatDemoRequest

        req = ChatDemoRequest(
            user_text="随便说说", external_user_id="u1", conversation_id=CID
        )
        stub = _StubPersistence(read_raises=True)
        assert await conv_service._safety_locked(stub, req, "r1") is False

    @pytest.mark.asyncio
    async def test_anonymous_request_is_not_locked(self):
        """没有 external_user_id 就没有会话归属，查不了也不该锁。"""
        from app.domain.conversation.schemas import ChatDemoRequest

        req = ChatDemoRequest(user_text="随便说说", conversation_id=CID)
        assert (
            await conv_service._safety_locked(_StubPersistence(True), req, "r1")
            is False
        )


class TestLockIsWrittenOnlyForCrisis:
    @pytest.mark.asyncio
    async def test_crisis_writes_the_lock_at_s3(self):
        from app.domain.conversation.schemas import ChatDemoRequest

        p = _StubPersistence()
        req = ChatDemoRequest(user_text="我已经想好了", external_user_id="u1")
        await conv_service._lock_session_after_crisis(
            p, req, CID, "crisis_keyword", "r1"
        )
        assert p.lock_calls == [(CID, "S3")]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "flag", ["ok", "blocked_keyword", "illegal_keyword", "low_quality_keyword"]
    )
    async def test_other_safety_flags_never_lock(self, flag: str):
        """只有危机才锁。普通敏感内容命中不该让整个会话停掉——
        那类的处置是换个话题继续，不是终止陪伴。"""
        from app.domain.conversation.schemas import ChatDemoRequest

        p = _StubPersistence()
        req = ChatDemoRequest(user_text="随便", external_user_id="u1")
        await conv_service._lock_session_after_crisis(p, req, CID, flag, "r1")
        assert p.lock_calls == []

    @pytest.mark.asyncio
    async def test_no_conversation_id_means_nothing_to_lock(self):
        """首轮落库失败时 conversation_id 是 None，没有东西可锁。"""
        from app.domain.conversation.schemas import ChatDemoRequest

        p = _StubPersistence()
        req = ChatDemoRequest(user_text="我已经想好了", external_user_id="u1")
        await conv_service._lock_session_after_crisis(
            p, req, None, "crisis_keyword", "r1"
        )
        assert p.lock_calls == []


class TestNoAutoUnlock:
    """不提供解锁接口——不该由模型判断"他现在好些了"来解除。"""

    def test_persistence_protocol_has_no_unlock(self):
        from app.domain.conversation.persistence import ConversationPersistence

        names = dir(ConversationPersistence)
        assert not [n for n in names if "unlock" in n.lower()]
