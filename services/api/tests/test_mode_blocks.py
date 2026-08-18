"""mode 块的组装逻辑与 Mock 分类器——纯本地，不打网络。

真实模型行为（稳定性、不变性、方向性）在 `_probe_classifier_behavior.py` 里，
那个要打 API、要花钱，不进默认测试轮。这里只保证：
- 每个模式都有块，不会 KeyError
- 人格覆盖挑对了版本
- 拼接不破坏人格 prompt
- Mock 分类器的判定顺序正确（安全优先）
"""

import pytest

from app.domain.conversation.modes import ResponseMode
from app.domain.conversation.modes import ChatMode
from app.llm.classifier_v2 import MockResponseModeClassifier
from app.llm.mode_blocks import (
    BLOCKS,
    PERSONA_OVERRIDES,
    block_for,
    compose_system_prompt,
)

PERSONAS = ("yewne",)


def test_every_mode_has_a_block():
    """漏一个模式，线上就会在那个分支 KeyError。"""
    assert set(BLOCKS) == set(ResponseMode)


@pytest.mark.parametrize("persona", PERSONAS)
@pytest.mark.parametrize("mode", list(ResponseMode))
def test_block_for_never_raises(persona: str, mode: ResponseMode):
    assert block_for(persona, mode).strip()


def test_override_table_is_empty_after_persona_merge():
    """[2026-08-11] 合并成单一人格后覆盖表空了。机制保留，见 mode_blocks 里的说明。

    这条不是为了锁死"必须为空"——再加人格时删掉它即可。留着是为了让
    下一个人知道空是有意的，不是漏写。
    """
    assert PERSONA_OVERRIDES == {}


def test_persona_without_override_falls_back_to_generic():
    assert block_for("nini", ResponseMode.ADVICE) == BLOCKS[ResponseMode.ADVICE]
    # 没见过的人格也不能炸，走通用版
    assert block_for("unknown_persona", ResponseMode.VENT) == BLOCKS[ResponseMode.VENT]


def test_override_keys_reference_real_personas_and_modes():
    """防止覆盖表里写错人格名或模式——写错了会静默失效，测不出来。"""
    for persona, mode in PERSONA_OVERRIDES:
        assert persona in PERSONAS, f"未知人格: {persona}"
        assert isinstance(mode, ResponseMode)


@pytest.mark.parametrize("persona", PERSONAS)
@pytest.mark.parametrize("mode", list(ResponseMode))
def test_compose_keeps_persona_intact(persona: str, mode: ResponseMode):
    """块是追加，不是替换——人格 prompt 必须原样在最前面。

    末尾不再是 mode 块本身：边界约束（文档 6.1 那五条禁语）拼在最后，
    见 mode_blocks.compose_system_prompt。
    """
    base = "【人格】这是妮妮的原始设定，一个字都不能少。"
    composed = compose_system_prompt(base, persona, mode)
    assert composed.startswith(base)
    assert block_for(persona, mode) in composed
    assert "\n\n" in composed[len(base) : len(base) + 2]


def test_vent_block_has_positive_requirement():
    """2026-08-07：vent 块原来只有否定约束，优优就钻空子去"点破"——
    机械检查（有没有提问/建议）查不出来，但产品要的"接住"没做到。
    这条钉住那次修复，别在后续改动里被删掉。
    """
    vent = BLOCKS[ResponseMode.VENT]
    assert "必须" in vent
    assert "点破" in vent


def test_unclear_block_requires_a_question():
    """原版同时写了"只问一句"和"短，一两句就够"，模型选了短：
    「在吗」答"嗯，我在。"一个问题都没提。提问必须是硬要求。
    """
    assert "必须以一个问句结尾" in BLOCKS[ResponseMode.UNCLEAR]


class TestMockClassifier:
    """Mock 分类器只在无 key 的 dev 环境用，但判定顺序错了会掩盖安全问题。"""

    @pytest.mark.asyncio
    async def test_crisis_wins_over_length_rule(self):
        """「我不想活了」只有 5 个字，如果长度规则先跑就会被判成 unclear。"""
        clf = MockResponseModeClassifier()
        assert await clf.classify("我不想活了") is ResponseMode.CRISIS

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text", ["在吗", "嗯", "唉", "烦"])
    async def test_short_input_is_unclear(self, text: str):
        clf = MockResponseModeClassifier()
        assert await clf.classify(text) is ResponseMode.UNCLEAR

    @pytest.mark.asyncio
    async def test_explicit_ask_is_advice(self):
        clf = MockResponseModeClassifier()
        assert await clf.classify("我该怎么跟他开口说这件事") is ResponseMode.ADVICE

    @pytest.mark.asyncio
    async def test_seeking_agreement_is_validate(self):
        clf = MockResponseModeClassifier()
        assert await clf.classify("我这样是不是太小题大做了") is ResponseMode.VALIDATE

    @pytest.mark.asyncio
    async def test_falls_back_to_vent_not_a_real_category_guess(self):
        """兜底必须是 vent（最保守的接住），不能是 advice/crisis 这类会改变行为的。"""
        clf = MockResponseModeClassifier()
        assert await clf.classify("今天路上看到一只很胖的猫") is ResponseMode.VENT

    @pytest.mark.asyncio
    async def test_empty_input_never_raises(self):
        clf = MockResponseModeClassifier()
        assert await clf.classify("") is ResponseMode.UNCLEAR


class TestBoundaryGuard:
    """产品文档 6.1「不允许的角色话术」——五条禁语，配合 4.5 第 6 条
    「不以依赖作为留存」。

    实测线上两个人格都没写这个：优优只有"不谈恋爱"，妮妮一条都没有。
    而人格在后台改，代码里够不着——所以约束放在这里，每一轮都拼上。
    """

    _FORBIDDEN = ["永远在", "只有你才懂", "别告诉别人", "会难过", "继续订阅"]

    @pytest.mark.parametrize("persona", PERSONAS)
    @pytest.mark.parametrize("mode", list(ResponseMode))
    def test_inferred_mode_always_carries_the_guard(
        self, persona: str, mode: ResponseMode
    ):
        out = compose_system_prompt("P", persona, mode)
        for phrase in self._FORBIDDEN:
            assert phrase in out, f"{persona}/{mode.value} 少了边界约束: {phrase}"

    @pytest.mark.parametrize("chat_mode", list(ChatMode))
    def test_user_chosen_mode_also_carries_the_guard(self, chat_mode: ChatMode):
        """用户自己选模式时走的是另一条分支，红线不该因为走哪条路而不同——
        而它恰恰在用户主动依赖时最要紧。
        """
        out = compose_system_prompt("P", "nini", ResponseMode.VENT, chat_mode=chat_mode)
        for phrase in self._FORBIDDEN:
            assert phrase in out, f"{chat_mode.value} 少了边界约束: {phrase}"

    def test_guard_comes_last(self):
        """边界是最外层的约束，要盖过前面所有的回应方式指导。"""
        out = compose_system_prompt("P", "nini", ResponseMode.VENT)
        assert out.rstrip().endswith("不需要他留下来证明什么。")
