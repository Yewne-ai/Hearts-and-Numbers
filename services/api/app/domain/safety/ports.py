"""紧急联系人与短信通道的接口占位——对齐产品文档 8.5。

## 为什么现在只有接口

这两件事都落不了地：

- **联系人存取**要数据库，而 `PERSISTENCE_ENABLED` 现在是 false，
  开发和生产都还没有 Postgres。
- **发短信**要一条独立的供应商通道。文档 8.5.3 明确要求它
  「使用独立模板、独立供应商配置和独立限流，**不复用登录验证码模板**」，
  所以不能直接拿 `app/sms/aliyun.py` 那套来用。

决策逻辑（该不该发、发几次、幂等键）不依赖这两样，已经在 `escalation.py`
里写完并测过。这里定好形状，等基础设施到位直接实现，不用回头改调用方。

## 实现这两个接口时必须守住的

`ports.py` 只是形状，下面这些是文档里的硬约束，实现的人要照着做：

1. **短信内容最小化**（8.5.2）——不得写入小六壬结果、心事原文、诊断词、
   具体自伤方式或第三方隐私。模板固定，只带联系人称呼。
2. **只发给 verified 且未撤回的联系人**（8.5.1 第 5 条）。
3. **幂等**（10.2）——用 `escalation.idempotency_key()`，防模型重试造成重复短信。
4. **手机号加密存储，普通后台只显示后四位**（8.5.1 第 4 条）。
5. **失败最多重试一次**（8.5.2），然后如实告诉用户未送达。
6. **审计日志不可被普通运营人员修改**（8.9 最后一条）。
"""

from typing import Protocol

from app.domain.safety.escalation import ContactStatus


class EmergencyContactReader(Protocol):
    """读紧急联系人状态。写入/验证流程是另一条链路，不在这里。

    只暴露决策需要的那一点信息——决策逻辑不需要知道手机号，
    也就不该有拿到手机号的能力。
    """

    async def status_for(self, external_user_id: str) -> ContactStatus:
        """该用户的紧急联系人当前状态。没设置过返回 `ContactStatus.NONE`。"""
        ...


class EmergencySmsNotifier(Protocol):
    """发紧急联系人短信。**不是**登录验证码那条通道（文档 8.5.3）。"""

    async def send(
        self,
        *,
        contact_id: str,
        idempotency_key: str,
        template_version: str,
        high_priority: bool,
    ) -> str:
        """创建发送任务，返回供应商消息 ID 供查送达。

        注意签名里**没有消息正文**——内容由 `template_version` 决定，
        调用方不能自由拼文案。这是防止心事原文顺着参数漏进短信里
        （文档 8.5.2 的内容最小化要求）最直接的办法。
        """
        ...


class UnavailableContactReader:
    """占位实现：永远返回"没有可用联系人"。

    在数据库接好之前，这是**唯一诚实**的答案——我们确实读不到联系人。
    返回 NONE 会让 `decide_notification` 走 NO_CONTACT 分支，前端据此
    持续显示一键拨号 110/120/12356，而不是伪装成"已通知"（文档 8.5.2）。
    """

    async def status_for(self, external_user_id: str) -> ContactStatus:
        return ContactStatus.NONE


class DisabledSmsNotifier:
    """占位实现：明确抛错，不静默吞掉。

    静默成功是这里最危险的失败方式——前端会显示"已通知紧急联系人"，
    而实际上什么都没发生。宁可报错让调用方处理成"未送达"。
    """

    async def send(
        self,
        *,
        contact_id: str,
        idempotency_key: str,
        template_version: str,
        high_priority: bool,
    ) -> str:
        raise NotImplementedError(
            "紧急短信通道尚未接入：需要独立的供应商配置（不复用登录验证码模板，"
            "见产品文档 8.5.3）。在此之前调用方应按'未送达'处理，"
            "并继续提供直接拨号入口。"
        )
