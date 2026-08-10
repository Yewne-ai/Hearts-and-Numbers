"""用户偏好的计算与作用范围——纯本地,不碰数据库也不打网络。

这套测试的重点不是"算得对不对",是**边界守没守住**:
- crisis / concern 绝不参与偏好（既不计入，也不受影响）
- 样本不够、或两类接近时，不许贴标签
- 偏好只能改 unclear 的问法，不能碰别的模式
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.preference.schemas import (
    LEANABLE_MODES,
    MIN_EVENTS_FOR_LEAN,
    Lean,
    ModeEvent,
    ModePreference,
)
from app.domain.preference.service import compute_preference, should_personalize
from app.domain.conversation.modes import ResponseMode
from app.llm.mode_blocks import compose_system_prompt, unclear_hint_for

_T0 = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def events(*modes: ResponseMode, user: str = "u1") -> list[ModeEvent]:
    return [
        ModeEvent(external_user_id=user, mode=m, occurred_at=_T0 + timedelta(minutes=i))
        for i, m in enumerate(modes)
    ]


class TestSafetyBoundary:
    """安全类不参与个性化——这几条是硬线，改坏了要能立刻测出来。"""

    def test_crisis_and_concern_are_not_leanable(self):
        assert ResponseMode.CRISIS not in LEANABLE_MODES
        assert ResponseMode.CONCERN not in LEANABLE_MODES

    def test_crisis_events_never_count_toward_lean(self):
        """满屏 crisis 也不该产生任何倾向——否则一个反复陷入危机的用户
        会被贴上"危机型"标签，然后被区别对待。"""
        pref = compute_preference(events(*([ResponseMode.CRISIS] * 50)))
        assert pref.lean is Lean.NONE
        assert pref.total == 0

    def test_crisis_events_do_not_dilute_real_counts(self):
        """混进来的 crisis 不该把可计数事件的总数撑大，从而提前触发倾斜。"""
        mixed = events(*([ResponseMode.CRISIS] * 20), *([ResponseMode.VENT] * 3))
        assert compute_preference(mixed).lean is Lean.NONE

    @pytest.mark.parametrize(
        "mode", [m for m in ResponseMode if m is not ResponseMode.UNCLEAR]
    )
    def test_personalization_only_applies_to_unclear(self, mode: ResponseMode):
        assert should_personalize(mode) is False

    def test_unclear_is_personalizable(self):
        assert should_personalize(ResponseMode.UNCLEAR) is True

    @pytest.mark.parametrize("lean", ["vent", "advice", "validate"])
    @pytest.mark.parametrize(
        "mode", [m for m in ResponseMode if m is not ResponseMode.UNCLEAR]
    )
    def test_lean_cannot_leak_into_other_modes(self, mode: ResponseMode, lean: str):
        """就算调用方传了 lean，非 unclear 的模式也必须原样输出。"""
        with_lean = compose_system_prompt("P", "nini", mode, lean)
        without = compose_system_prompt("P", "nini", mode, "none")
        assert with_lean == without


class TestColdStart:
    def test_no_events_is_none(self):
        assert compute_preference([]).lean is Lean.NONE

    def test_below_threshold_never_leans(self):
        """哪怕 100% 一边倒，样本不够也不许贴标签——三条记录看不出人格。"""
        few = events(*([ResponseMode.VENT] * (MIN_EVENTS_FOR_LEAN - 1)))
        assert compute_preference(few).lean is Lean.NONE

    def test_unclear_does_not_count_as_a_preference(self):
        """unclear 是"没有信号"，不是一种偏好。计进去会让沉默的用户
        越来越被当成沉默的用户。"""
        pref = compute_preference(events(*([ResponseMode.UNCLEAR] * 50)))
        assert pref.lean is Lean.NONE
        assert pref.total == 0


class TestLeanDetection:
    def test_clear_majority_leans(self):
        pref = compute_preference(
            events(*([ResponseMode.VENT] * 12), *([ResponseMode.ADVICE] * 2))
        )
        assert pref.lean is Lean.VENT
        assert pref.counts[ResponseMode.VENT] == 12

    def test_near_tie_does_not_lean(self):
        """两类几乎持平时选谁都是抛硬币，不如不选。"""
        pref = compute_preference(
            events(*([ResponseMode.VENT] * 7), *([ResponseMode.VALIDATE] * 6))
        )
        assert pref.lean is Lean.NONE

    def test_evenly_spread_does_not_lean(self):
        pref = compute_preference(
            events(
                *([ResponseMode.VENT] * 5),
                *([ResponseMode.ADVICE] * 5),
                *([ResponseMode.VALIDATE] * 5),
            )
        )
        assert pref.lean is Lean.NONE

    def test_validate_lean_detected(self):
        pref = compute_preference(
            events(*([ResponseMode.VALIDATE] * 11), *([ResponseMode.VENT] * 3))
        )
        assert pref.lean is Lean.VALIDATE


class TestUnclearHint:
    @pytest.mark.parametrize("lean", ["vent", "advice", "validate"])
    def test_each_lean_has_a_distinct_hint(self, lean: str):
        assert unclear_hint_for(lean).strip()

    @pytest.mark.parametrize("lean", ["none", "", "unknown", "crisis", "concern"])
    def test_unknown_lean_adds_nothing(self, lean: str):
        assert unclear_hint_for(lean) == ""

    def test_hint_never_removes_the_question_requirement(self):
        """问法可以变，"必须以问句结尾"这条硬要求在所有变体里都得保留。"""
        for lean in ("none", "vent", "advice", "validate"):
            out = compose_system_prompt("P", "nini", ResponseMode.UNCLEAR, lean)
            assert "必须以一个问句结尾" in out

    def test_empty_preference_helper(self):
        empty = ModePreference.empty()
        assert empty.lean is Lean.NONE
        assert empty.total == 0
