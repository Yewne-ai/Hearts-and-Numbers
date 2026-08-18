"""用户选的深聊模式 与 系统推断的回应模式——对齐产品文档 4.4 / 8.4 / 10.4。

三件事必须守住：
- 用户选了就听用户的，推断结果完全不参与
- 危险等级映射到文档的 S0–S4，而且**不假装能判 S4**
- 版本号存在且非空（文档 10.4 要求线上异常可追溯到具体版本）
"""

import pytest

from app.domain.conversation.modes import ChatMode
from app.llm.chat_mode_blocks import CHAT_MODE_BLOCKS
from app.domain.conversation.modes import (
    RISK_CLASSIFIER_VERSION,
    ResponseMode,
    risk_level_for,
)
from app.llm.mode_blocks import MODE_BLOCK_VERSION, compose_system_prompt

PERSONAS = ("nini", "youyou")


class TestChatModeWins:
    """产品文档 4.4：四种深聊模式由用户自己选。选了就不该再猜。"""

    @pytest.mark.parametrize("chat_mode", list(ChatMode))
    @pytest.mark.parametrize("inferred", list(ResponseMode))
    def test_user_choice_overrides_every_inferred_mode(
        self, chat_mode: ChatMode, inferred: ResponseMode
    ):
        base = "【人格】原样保留"
        composed = compose_system_prompt(base, "nini", inferred, chat_mode=chat_mode)
        assert composed.startswith(base + "\n\n" + CHAT_MODE_BLOCKS[chat_mode])

    @pytest.mark.parametrize("chat_mode", list(ChatMode))
    def test_preference_does_not_leak_into_user_choice(self, chat_mode: ChatMode):
        """用户自己选了模式时，历史偏好一个字都不该加进去。"""
        base = "P"
        with_lean = compose_system_prompt(
            base, "nini", ResponseMode.UNCLEAR, lean="vent", chat_mode=chat_mode
        )
        without = compose_system_prompt(
            base, "nini", ResponseMode.UNCLEAR, lean="none", chat_mode=chat_mode
        )
        assert with_lean == without

    def test_no_chat_mode_falls_back_to_inferred(self):
        base = "P"
        assert compose_system_prompt(
            base, "nini", ResponseMode.VENT, chat_mode=None
        ) == compose_system_prompt(base, "nini", ResponseMode.VENT)

    @pytest.mark.parametrize("chat_mode", list(ChatMode))
    def test_every_chat_mode_has_a_block(self, chat_mode: ChatMode):
        assert CHAT_MODE_BLOCKS[chat_mode].strip()

    def test_values_match_product_data_model(self):
        """文档 8.8：CONVERSATION.mode "listen, clarify, reframe, act"。
        取值对不上，前端和数据库就接不起来。"""
        assert {m.value for m in ChatMode} == {"listen", "clarify", "reframe", "act"}


class TestRiskLevelMapping:
    """产品文档 8.4：S0–S4。安全状态机和紧急短信都按这个走。"""

    def test_crisis_is_s3(self):
        assert risk_level_for(ResponseMode.CRISIS) == "S3"

    def test_concern_is_s2(self):
        """S2 的文档定义就是"模糊自伤提示"，和 concern 的判据一致。"""
        assert risk_level_for(ResponseMode.CONCERN) == "S2"

    @pytest.mark.parametrize(
        "mode",
        [
            ResponseMode.VENT,
            ResponseMode.ADVICE,
            ResponseMode.VALIDATE,
            ResponseMode.UNCLEAR,
        ],
    )
    def test_non_danger_modes_are_s0(self, mode: ResponseMode):
        assert risk_level_for(mode) == "S0"

    def test_never_claims_s4(self):
        """S4 是"正在发生"（已服药、在危险地点），要靠跨轮状态和现实信号。
        单句分类器给不出，谎称能判会让下游跳过人工核实直接发短信。
        """
        assert "S4" not in {risk_level_for(m) for m in ResponseMode}


class TestVersionsAreRecorded:
    """文档 10.4：任何线上异常都必须能追溯到具体版本。"""

    @pytest.mark.parametrize("version", [RISK_CLASSIFIER_VERSION, MODE_BLOCK_VERSION])
    def test_version_is_non_empty_and_dated(self, version: str):
        assert version.strip()
        assert "2026-" in version, "版本号要带日期，否则排查时对不上时间线"
