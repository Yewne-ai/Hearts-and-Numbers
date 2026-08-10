"""现实求助入口与安全确认——对齐产品文档 8.5.2。

## 这套测试守的是一个取舍

文档 8.4 要求 S2「进入安全确认流程」（直接问一句），而 concern 块写的是
「不要说破」。解法是把两件事分开：**回复层不说破，入口挂在界面上**。

所以这里最重要的一条是 `test_concern_stays_quiet`——S2 的入口必须是
安静的。一旦它变成显眼的东西，就退化成了 concern 块特意避免的"说破"。
"""

import pytest
from fastapi.testclient import TestClient

from app.domain.safety.care import (
    HOTLINES,
    CareLevel,
    affordance_for,
)
from app.domain.safety.escalation import NotificationDecision
from app.main import app

client = TestClient(app)


class TestAffordanceLevel:
    def test_normal_shows_nothing(self):
        assert (
            affordance_for(risk_level="S0", session_locked=False).level
            is CareLevel.NONE
        )

    def test_concern_stays_quiet(self):
        """S2 的入口必须安静——这是"不说破"和"要确认"之间的整个取舍所在。
        改成 PROMINENT 就等于让界面替 AI 把话说破了。
        """
        assert (
            affordance_for(risk_level="S2", session_locked=False).level
            is CareLevel.QUIET
        )

    @pytest.mark.parametrize("level", ["S3", "S4"])
    def test_explicit_risk_is_prominent(self, level: str):
        assert (
            affordance_for(risk_level=level, session_locked=False).level
            is CareLevel.PROMINENT
        )

    def test_locked_session_is_always_prominent(self):
        """会话已锁时把入口藏起来说不过去——文档 8.6 里 Safety 是终态。"""
        a = affordance_for(risk_level="S0", session_locked=True)
        assert a.level is CareLevel.PROMINENT

    @pytest.mark.parametrize("level", ["S2", "S3", "S4"])
    def test_hotlines_always_present_when_shown(self, level: str):
        """文档 8.5.2：无可用联系人时不伪装成已求助，持续显示一键拨号。
        所以只要显示入口，号码就必须在——它不是备选方案，是底线。
        """
        a = affordance_for(risk_level=level, session_locked=False)
        assert a.hotlines == list(HOTLINES)
        assert a.confirm_path

    def test_affordance_carries_no_reason_or_quote(self):
        """入口里不含判断依据和原文——知道了只会让界面多出解释的冲动，
        而解释就是说破。"""
        dumped = affordance_for(risk_level="S2", session_locked=False).model_dump()
        assert set(dumped) == {"level", "hotlines", "confirm_path"}


class TestHotlineRegistry:
    def test_emergency_numbers_are_present(self):
        """文档 8.5.2 点名的三个号码。"""
        numbers = {h.number for h in HOTLINES}
        assert {"110", "120", "12356"} <= numbers

    def test_every_hotline_has_a_label(self):
        """光有号码没有说明，用户不知道该打哪个。"""
        for h in HOTLINES:
            assert h.label.strip()


class TestConfirmEndpoint:
    """让 decide_notification 有真实调用方——在这之前它是死代码。"""

    def _post(self, answer: str, level: str = "S3"):
        return client.post(
            "/v1/safety/confirm",
            json={"external_user_id": "u1", "answer": answer, "risk_level": level},
        ).json()

    @pytest.mark.parametrize("answer", ["need_help", "im_ok", "dismissed"])
    def test_s2_never_notifies(self, answer: str):
        """文档 8.5.2 第一行：S0–S2 一律不自动发送，答什么都一样。"""
        body = self._post(answer, "S2")
        assert body["decision"] == NotificationDecision.NOT_ELIGIBLE.value

    def test_s3_without_contact_reports_no_contact_not_notify(self):
        """没有紧急联系人时返回 no_contact 而不是 notify——
        这不是待办，是文档 8.5.2 要求的"不伪装成已求助"。"""
        body = self._post("need_help", "S3")
        assert body["decision"] == NotificationDecision.NO_CONTACT.value

    def test_im_ok_at_s3_still_counts_as_confirmed(self):
        """说出口的意图不该被一次点击抹掉——回避正是这种时候最常见的反应。"""
        assert "confirmed_s3" in self._post("im_ok", "S3")["reason_code"]

    def test_dismissed_records_its_own_basis(self):
        """ "关掉了"和"回答了"在文档 8.5.2 里是两种不同的依据，日志里要分得开。"""
        assert "no_response" in self._post("dismissed", "S3")["reason_code"]

    @pytest.mark.parametrize("answer", ["need_help", "im_ok", "dismissed"])
    def test_hotlines_returned_regardless_of_decision(self, answer: str):
        """现实求助入口要持续显示，不因为"已经处理了"就收起来。"""
        assert len(self._post(answer)["hotlines"]) == len(HOTLINES)

    def test_free_text_answer_is_rejected(self):
        """答案刻意做成三选一：这个值直接参与是否惊动紧急联系人的决策，
        不该让模型去解释一段话再映射（文档 10.9）。"""
        r = client.post(
            "/v1/safety/confirm",
            json={"external_user_id": "u1", "answer": "我还好吧", "risk_level": "S2"},
        )
        assert r.status_code == 422

    def test_invalid_risk_level_is_rejected(self):
        r = client.post(
            "/v1/safety/confirm",
            json={"external_user_id": "u1", "answer": "im_ok", "risk_level": "S9"},
        )
        assert r.status_code == 422
