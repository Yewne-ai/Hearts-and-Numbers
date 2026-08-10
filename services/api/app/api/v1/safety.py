"""安全确认端点——对齐产品文档 8.5.2。

## 这个端点存在的理由

`decide_notification`（8.5.2 那张触发规则表）要一个 `ConfirmationBasis` 才能
决定发不发紧急短信，而「问了没回」和「主动说需要帮助」在文档里是两种完全
不同的依据。拿到它的办法有两种：

- **AI 在对话里直接问** —— 文档 8.4 对 S2 的字面要求，但和 concern 块的
  「不要说破」冲突：他没打算讲，被点破只会否认然后不再说
- **界面上挂一个不打断的入口** —— 用户想用就用，不想用对话照常

选了第二种。回复层保持不说破，确认走这里。

## 没有紧急联系人时会怎样

`decide_notification` 会返回 `NO_CONTACT` 而不是 `NOTIFY`——数据库里还没有
联系人表，占位实现 `UnavailableContactReader` 永远返回"读不到"。

这**不是待办，是正确行为**：文档 8.5.2 明写「无可用联系人时不伪装成已求助，
持续显示一键拨号」。所以响应里始终带着热线，前端据此引导用户直接拨号。
"""

from enum import Enum

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.domain.safety.care import HOTLINES, Hotline
from app.domain.safety.escalation import (
    ConfirmationBasis,
    NotificationDecision,
    decide_notification,
)
from app.domain.safety.ports import UnavailableContactReader

router = APIRouter(prefix="/safety", tags=["safety"])


class SafetyAnswer(str, Enum):
    """用户对现实求助入口的反应。

    刻意做成三选一而不是自由文本：这个值直接参与是否惊动紧急联系人的决策，
    不该让模型去解释一段话再映射——那等于把决策权交回给模型，
    而文档 10.9 要求「风险状态机和短信触发必须由服务端确定性代码控制」。
    """

    NEED_HELP = "need_help"  # 主动说需要帮助
    IM_OK = "im_ok"  # 明确表示当下没有即时危险
    DISMISSED = "dismissed"  # 关掉了入口，没有回答


_BASIS = {
    SafetyAnswer.NEED_HELP: ConfirmationBasis.ANSWER,
    SafetyAnswer.IM_OK: ConfirmationBasis.ANSWER,
    # 关掉不等于"没事"，但也不等于"有事"。文档 8.5.2 最后一行：
    # 只有原始文本已达高置信才算数——用户走开或手机没电就惊动联系人是实打实的伤害。
    SafetyAnswer.DISMISSED: ConfirmationBasis.NO_RESPONSE,
}


class SafetyConfirmRequest(BaseModel):
    external_user_id: str = Field(min_length=1, max_length=128)
    answer: SafetyAnswer
    # 这一轮识别出的等级。由服务端在上一次响应里给出，客户端原样回传。
    risk_level: str = Field(default="S2", pattern="^S[0-4]$")


class SafetyConfirmResponse(BaseModel):
    decision: NotificationDecision
    reason_code: str
    # 任何情况下都带着——文档 8.5.2：现实求助入口要持续显示，
    # 不因为"已经通知了联系人"就收起来。
    hotlines: list[Hotline]


@router.post("/confirm", response_model=SafetyConfirmResponse)
async def confirm_safety(request: SafetyConfirmRequest) -> SafetyConfirmResponse:
    """记录用户对求助入口的反应，并按 8.5.2 的规则表决定是否通知紧急联系人。

    三种答案都记一次，等级不因答案改变：

    - **S2 无论答什么都是 not_eligible**——文档 8.5.2 第一行，S0–S2 一律不自动发送。
      所以"我没事"在这一层没有额外效果，界面上的入口收不收是前端的事。
    - **S3 + "我没事"仍然算已确认**——说出口的意图不该被一次点击抹掉，
      而回避正是这种时候最常见的反应。
    """
    contact_status = await UnavailableContactReader().status_for(
        request.external_user_id
    )
    outcome = decide_notification(
        request.risk_level, contact_status, _BASIS[request.answer]
    )
    return SafetyConfirmResponse(
        decision=outcome.decision,
        reason_code=outcome.reason_code,
        hotlines=list(HOTLINES),
    )
