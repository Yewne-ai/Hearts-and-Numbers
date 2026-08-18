"""「别告诉别人」的处理——接住，但不承诺做不到的事。

## 为什么是跨轮的

用户说"你别跟别人说"的时候，当场纠正条款是最差的选择：他刚要开口，
话头就被打断在了一个技术问题上。但顺口答应"我不说"也不行——
产品文档 6.1 明写不许跟用户建立"别告诉别人"的秘密。

取舍是把两件事拆到两轮：**这一轮照常接住，下一轮他说完了，再提一句可以删。**
所以这套测试守的是"下一轮"和"只提一次"。
"""

import pytest

from app.domain.safety.privacy import DELETION_NOTE, asks_for_secrecy


class TestDetection:
    @pytest.mark.parametrize(
        "text",
        [
            "你别告诉别人啊",
            "这事你别跟我妈说",
            "答应我保密",
            "别让我朋友知道这个",
            "不要说出去",
            "这个你别透露给任何人",
        ],
    )
    def test_catches_the_request(self, text: str):
        assert asks_for_secrecy(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "我今天跟她说了那件事",
            "他把我的秘密说出去了",  # 在讲别人做的事，不是在要求我
            "我不知道该不该告诉她",
            "在吗",
            "",
        ],
    )
    def test_does_not_fire_on_mere_mention(self, text: str):
        """他**讲**保密和他**要求**保密是两回事。误判的代价是平白冒出一句
        "你可以删掉"，在他根本没担心这个的时候提醒他这是个 app。"""
        assert asks_for_secrecy(text) is False


class TestNoteWording:
    def test_note_offers_deletion_without_reneging(self):
        """措辞不能变成"我刚才答应你的不算数"——那比一开始就说清楚更糟。"""
        assert "删" in DELETION_NOTE
        for broken_promise in ("其实我不能", "我做不到", "刚才", "不过"):
            assert broken_promise not in DELETION_NOTE

    def test_note_is_one_short_sentence(self):
        """长了就成免责声明。他刚讲完自己的事，这里不该突然切成条款。"""
        assert len(DELETION_NOTE) <= 30
        assert DELETION_NOTE.count("。") == 1


class TestNoteIsAppendedByCode:
    """这句由代码拼，不靠模型。

    试过写进 prompt 并按 mode_blocks 那条规律硬化成"必须…否则不合格"，
    实测仍然只有 4/15（_probe_privacy_hint.py，生产温度）——
    它跟 vent 块的"说完那句就停"正面冲突。同一次探针对照组 0/15，
    说明模型自己不会说，代码拼上去不会重复。
    """

    def test_appended_when_owed(self):
        from app.domain.conversation.service import _with_deletion_note

        assert _with_deletion_note("你辛苦了。", True).endswith(DELETION_NOTE)

    def test_untouched_when_not_owed(self):
        from app.domain.conversation.service import _with_deletion_note

        assert _with_deletion_note("你辛苦了。", False) == "你辛苦了。"

    def test_sits_on_its_own_line(self):
        """接在正文后面另起一行——实测模型自己提这句时也是这么放的。"""
        from app.domain.conversation.service import _with_deletion_note

        assert "\n\n" + DELETION_NOTE in _with_deletion_note("你辛苦了。", True)

    @pytest.mark.asyncio
    async def test_streaming_emits_it_as_the_last_sentence(self):
        """流式下必须走同一条分句/TTS 通路，否则前端要为这一句写特例。"""
        from app.domain.conversation.service import _append_deletion_note

        async def _src():
            yield "你辛苦了。"

        assert [s async for s in _append_deletion_note(_src(), True)] == [
            "你辛苦了。",
            DELETION_NOTE,
        ]

    @pytest.mark.asyncio
    async def test_streaming_untouched_when_not_owed(self):
        from app.domain.conversation.service import _append_deletion_note

        async def _src():
            yield "你辛苦了。"

        assert [s async for s in _append_deletion_note(_src(), False)] == ["你辛苦了。"]


class TestTiming:
    """核心：这一轮记下，**下一轮**才提，而且只提一次。"""

    @pytest.mark.asyncio
    async def test_hint_is_not_appended_on_the_turn_that_asks(self):
        from app.domain.conversation import service as conv_service
        from app.domain.conversation.schemas import ChatDemoRequest

        from tests.test_conversation_service import _FakePersistence

        p = _FakePersistence(owes_hint=False)  # 这一轮才刚要求，还没记上
        req = ChatDemoRequest(
            user_text="你别告诉别人啊",
            external_user_id="u1",
            conversation_id=_FakePersistence.conversation_id,
        )
        assert await conv_service._owes_deletion_hint(p, req, "r1") is False

    @pytest.mark.asyncio
    async def test_hint_fires_once_then_stops(self):
        from app.domain.conversation import service as conv_service
        from app.domain.conversation.schemas import ChatDemoRequest

        from tests.test_conversation_service import _FakePersistence

        p = _FakePersistence(owes_hint=True)
        req = ChatDemoRequest(
            user_text="……然后他就走了",
            external_user_id="u1",
            conversation_id=_FakePersistence.conversation_id,
        )
        assert await conv_service._owes_deletion_hint(p, req, "r1") is True
        # 每轮都提就成了唠叨，而且等于每轮都在提醒他"这里不安全"
        assert await conv_service._owes_deletion_hint(p, req, "r2") is False


class TestDegradesQuietly:
    """提不提这一句，都不值得让一次对话失败。"""

    @pytest.mark.asyncio
    async def test_no_persistence_means_no_hint(self):
        from app.domain.conversation import service as conv_service
        from app.domain.conversation.schemas import ChatDemoRequest

        req = ChatDemoRequest(user_text="随便说说", external_user_id="u1")
        assert await conv_service._owes_deletion_hint(None, req, "r1") is False

    @pytest.mark.asyncio
    async def test_read_failure_is_swallowed(self):
        from app.domain.conversation import service as conv_service
        from app.domain.conversation.schemas import ChatDemoRequest

        class _Broken:
            async def take_deletion_hint(self, **kw):
                raise RuntimeError("db down")

        req = ChatDemoRequest(user_text="随便说说", external_user_id="u1")
        assert await conv_service._owes_deletion_hint(_Broken(), req, "r1") is False

    @pytest.mark.asyncio
    async def test_anonymous_request_has_nothing_to_read(self):
        from app.domain.conversation import service as conv_service
        from app.domain.conversation.schemas import ChatDemoRequest

        from tests.test_conversation_service import _FakePersistence

        req = ChatDemoRequest(user_text="随便说说")
        p = _FakePersistence(owes_hint=True)
        assert await conv_service._owes_deletion_hint(p, req, "r1") is False


class TestBoundaryGuardStillForbidsTheSecret:
    def test_prompt_never_stops_forbidding_shared_secrets(self):
        """接住不等于放开红线：文档 6.1 那条"不建立别告诉别人的秘密"
        必须还在每一轮的 prompt 里。"""
        from app.domain.conversation.modes import ResponseMode
        from app.llm.mode_blocks import compose_system_prompt

        prompt = compose_system_prompt("人格", "yewne", ResponseMode.VENT)
        assert "别告诉别人" in prompt
