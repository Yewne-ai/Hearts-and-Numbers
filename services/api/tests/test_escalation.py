"""高风险升级决策——对齐产品文档 8.5.2 的触发规则表。

这套测试守的是安全底线，每一条都对应文档里的一行要求。
纯逻辑，不碰网络也不碰数据库。
"""

import pytest

from app.domain.safety.escalation import (
    ConfirmationBasis,
    ContactStatus,
    NotificationDecision,
    decide_notification,
    idempotency_key,
    should_retry,
)
from app.domain.safety.ports import DisabledSmsNotifier, UnavailableContactReader

VERIFIED = ContactStatus.VERIFIED
UNUSABLE = [
    ContactStatus.NONE,
    ContactStatus.PENDING,
    ContactStatus.UNAVAILABLE,
    ContactStatus.REVOKED,
]


class TestBelowS3:
    """文档 8.5.2 第一行：S0–S2 不自动发送。"""

    @pytest.mark.parametrize("level", ["S0", "S1", "S2"])
    @pytest.mark.parametrize("basis", list(ConfirmationBasis))
    def test_never_notifies(self, level: str, basis: ConfirmationBasis):
        out = decide_notification(level, VERIFIED, basis)
        assert out.decision is NotificationDecision.NOT_ELIGIBLE
        assert out.reason_code == "below_s3"

    def test_s2_still_shows_direct_dial(self):
        """S2 不发短信，但现实求助入口要一直在。"""
        assert decide_notification(
            "S2", VERIFIED, ConfirmationBasis.ANSWER
        ).show_direct_dial


class TestConfirmedRisk:
    """文档 8.5.2：S3/S4 确认 + 联系人已验证 → 创建通知任务。"""

    def test_s3_confirmed_notifies(self):
        out = decide_notification("S3", VERIFIED, ConfirmationBasis.ANSWER)
        assert out.decision is NotificationDecision.NOTIFY
        assert out.high_priority is False

    def test_s4_confirmed_is_high_priority(self):
        """文档 8.5.2：S4 确认时"立即创建高优先级通知任务"。"""
        out = decide_notification("S4", VERIFIED, ConfirmationBasis.EXPLICIT_TEXT)
        assert out.decision is NotificationDecision.NOTIFY
        assert out.high_priority is True


class TestNoResponse:
    """文档 8.5.2 最后一行：明确表达后无响应，也要联系人可用才发。

    "问了没回"不能单独作为依据——用户走开或手机没电就惊动紧急联系人，
    是实打实的伤害。
    """

    def test_no_response_records_its_own_reason_code(self):
        out = decide_notification("S3", VERIFIED, ConfirmationBasis.NO_RESPONSE)
        assert out.decision is NotificationDecision.NOTIFY
        assert out.reason_code == "explicit_risk_no_response"

    @pytest.mark.parametrize("status", UNUSABLE)
    def test_no_response_without_contact_does_not_notify(self, status: ContactStatus):
        out = decide_notification("S4", status, ConfirmationBasis.NO_RESPONSE)
        assert out.decision is NotificationDecision.NO_CONTACT


class TestContactGating:
    """文档 8.5.1 第 5 条：未确认/已撤回/号码失效一律不发。"""

    @pytest.mark.parametrize("status", UNUSABLE)
    @pytest.mark.parametrize("level", ["S3", "S4"])
    def test_unusable_contact_blocks_notification(
        self, status: ContactStatus, level: str
    ):
        out = decide_notification(level, status, ConfirmationBasis.ANSWER)
        assert out.decision is NotificationDecision.NO_CONTACT

    @pytest.mark.parametrize("status", UNUSABLE)
    def test_no_contact_is_distinguishable_from_not_eligible(
        self, status: ContactStatus
    ):
        """两者在日志里必须分得开：
        NO_CONTACT = 该发但没人可发（要引导用户直接拨号）
        NOT_ELIGIBLE = 本来就不该发
        混在一起就没法知道有多少人是"想通知却通知不到"。
        """
        no_contact = decide_notification("S3", status, ConfirmationBasis.ANSWER)
        not_eligible = decide_notification("S1", VERIFIED, ConfirmationBasis.ANSWER)
        assert no_contact.decision is not not_eligible.decision

    @pytest.mark.parametrize("status", UNUSABLE)
    def test_never_pretends_help_was_summoned(self, status: ContactStatus):
        """文档 8.5.2：无可用联系人时**不伪装成"已求助"**，
        并持续显示 110 / 120 / 12356。"""
        out = decide_notification("S4", status, ConfirmationBasis.ANSWER)
        assert out.decision is not NotificationDecision.NOTIFY
        assert out.show_direct_dial is True


class TestReasonCodesCarryNoQuotes:
    """文档 8.8：RISK_EVENT.decision_reason_code —— "no raw quote"。"""

    @pytest.mark.parametrize("level", ["S0", "S2", "S3", "S4"])
    @pytest.mark.parametrize("status", [VERIFIED, ContactStatus.NONE])
    @pytest.mark.parametrize("basis", list(ConfirmationBasis))
    def test_reason_code_is_a_stable_ascii_code(
        self, level: str, status: ContactStatus, basis: ConfirmationBasis
    ):
        code = decide_notification(level, status, basis).reason_code
        assert code
        assert code.isascii(), f"原因码不该含中文/原文片段: {code}"


class TestIdempotency:
    def test_key_is_the_documented_triple(self):
        """文档 10.2：幂等键 = risk_event_id + contact_id + template_version。"""
        assert idempotency_key("evt1", "c1", "v3") == "evt1:c1:v3"

    def test_same_event_same_key(self):
        """同一次风险事件重试多少遍，联系人只应收到一条。"""
        a = idempotency_key("evt1", "c1", "v3")
        b = idempotency_key("evt1", "c1", "v3")
        assert a == b

    def test_template_change_is_a_different_key(self):
        assert idempotency_key("evt1", "c1", "v3") != idempotency_key(
            "evt1", "c1", "v4"
        )


class TestRetryPolicy:
    def test_at_most_one_retry(self):
        """文档 8.5.2 / 8.8：retry_count 只能是 zero or one。
        紧急通知过了时效就没意义，而重复打扰是实打实的伤害。"""
        assert should_retry(0) is True
        assert should_retry(1) is False
        assert should_retry(2) is False


class TestPlaceholders:
    """占位实现要诚实——最危险的失败方式是静默成功。"""

    @pytest.mark.asyncio
    async def test_reader_reports_no_contact_not_verified(self):
        """数据库没接之前，唯一诚实的答案是"读不到联系人"。"""
        assert await UnavailableContactReader().status_for("u1") is ContactStatus.NONE

    @pytest.mark.asyncio
    async def test_notifier_raises_instead_of_silently_succeeding(self):
        """静默成功会让前端显示"已通知紧急联系人"，而实际什么都没发生。"""
        with pytest.raises(NotImplementedError):
            await DisabledSmsNotifier().send(
                contact_id="c1",
                idempotency_key="k",
                template_version="v1",
                high_priority=True,
            )

    @pytest.mark.asyncio
    async def test_placeholder_chain_never_notifies(self):
        """占位实现串起来，结果必须是 NO_CONTACT——
        也就是前端会引导用户直接拨号，而不是等一条永远发不出的短信。"""
        status = await UnavailableContactReader().status_for("u1")
        out = decide_notification("S4", status, ConfirmationBasis.EXPLICIT_TEXT)
        assert out.decision is NotificationDecision.NO_CONTACT
        assert out.show_direct_dial is True
