"""会话相关的 Pydantic schema。前后端共享语义在这里定义。

注意：枚举值要和未来 `packages/shared-types` 中的 TS union 字面量保持一致，
demo 阶段仅维护后端一份，前端按字符串字面量传入。
"""

from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.safety import SafetyReason
from app.domain.safety.care import CareAffordance


class Persona(str, Enum):
    """AI 陪伴人格。

    - youyou（优优）：毒舌损友，高洞察力
    - nini（妮妮）：白斗篷小精灵，知性直接，帮用户把问题变小
    """

    YOUYOU = "youyou"
    NINI = "nini"


class HistoryMessage(BaseModel):
    """单条历史消息，角色为 user 或 assistant。"""

    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=2000)


class ChatDemoRequest(BaseModel):
    """单轮 demo 请求，支持传入历史上下文。"""

    user_text: str = Field(
        ...,
        max_length=2000,
        description="用户本轮输入（最多 2000 字符）；空字符串会走 safety 兜底",
    )
    external_user_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="前端生成的匿名用户标识；缺省时不持久化本轮对话",
    )
    conversation_id: UUID | None = Field(
        default=None,
        description="后端返回的会话 ID；第一轮为空，后续轮次原样传回",
    )
    # [2026-08-03] 场景分类已移除。这个字段只为兼容线上老客户端(尤其是 Unity,
    # 他们的 YewneClient.cs 会在第二轮起回传 scene)——收下但完全不用,不再校验取值,
    # 也不再出现在响应里。老客户端因此不会吃 422,下次更新 zip 时自然清掉。
    # 删除前提:确认线上已无客户端发送此字段。
    scene: str | None = Field(
        default=None,
        deprecated=True,
        description="[已废弃] 收下即丢弃，保留仅为兼容老客户端",
    )
    persona: Persona = Field(
        default=Persona.NINI,
        description="AI 人格选择；默认 nini（妮妮），可切换为 youyou（优优）",
    )
    # [2026-07-29] 新增 max_length：原先只限制单条 content 2000 字符，条数完全不设限，
    # 一个请求可以塞进上千条历史并被原样转发给 DeepSeek 全额计费。
    # 阈值取 200 而非更紧的值：这一层只负责挡掉明显异常的请求（实测攻击是 800 条起），
    # 真正的成本控制由 service 层的 _MAX_HISTORY_CHARS 字符预算承担，所以这里可以给足
    # 余量、优先避免误伤真实长会话。超过 200 条即视为异常请求，直接 422。
    history: list[HistoryMessage] = Field(
        default_factory=list,
        max_length=200,
        description="当前浏览器会话的对话历史，不含本轮 user_text（最多 200 条）",
    )

    @field_validator("scene", mode="before")
    @classmethod
    def _empty_scene_is_none(cls, v: object) -> object:
        """空串当作未指定。Unity 的 JsonUtility 把 null 序列化成 ""，别让它吃 422。"""
        return None if v == "" else v

    @field_validator("conversation_id", mode="before")
    @classmethod
    def _empty_conversation_id_is_none(cls, v: object) -> object:
        """兼容把空会话 ID 序列化成空串的客户端。"""
        return None if v == "" else v


class ChatDemoResponse(BaseModel):
    """单轮 demo 响应。

    - `reply` 永远有值，前端可直接渲染；
    - `audio_base64` 音频与文字一起返回，省去前端的第二次请求；
    - `safety_flag` 用于前端判断是否在 UI 上加"建议联系信任的人"等提示；
    - `is_mock` 在 demo 阶段透明化，方便现场区分回复来源。
    """

    reply: str
    safety_flag: SafetyReason
    is_mock: bool
    request_id: str
    conversation_id: UUID | None = Field(
        default=None,
        description="已持久化的会话 ID；未启用或写入失败时为空",
    )
    degraded: bool = Field(
        default=False,
        description="true 表示原本走真模型但调用失败已降级到 Mock；前端可以加'临时离线'提示",
    )
    care: CareAffordance = Field(
        default_factory=CareAffordance,
        description=(
            "要不要显示现实求助入口、显示到什么程度。产品文档 8.5.2 要求 S2 以上"
            "持续显示，且无可用联系人时不伪装成已求助——所以这个字段是底线不是备选。"
        ),
    )
    mode: str = Field(
        default="",
        description=(
            "这一轮判定的回应模式（vent/advice/validate/crisis/concern/unclear）。"
            "RESPONSE_MODE_ENABLED 关闭时为空串。前端可不用，主要供日志和排查。"
        ),
    )
    audio_base64: str = Field(
        default="", description="MP3 base64；空串时前端降级浏览器朗读"
    )
    audio_content_type: str = Field(default="audio/mpeg")
    audio_is_mock: bool = Field(default=False)
    emotion: str = Field(default="", description="用户输入的情绪标签，空串表示未检测到")
    reaction: str = Field(
        default="",
        description=(
            "小人该播的反应动画，据于你这句回答判定；空串表示无（判定失败），"
            "前端回落 Idle。取值随人格：youyou=开心/伤心/疑惑/肯定/否定，nini=开心/伤心/疑惑/关心"
        ),
    )


class RoundSummary(BaseModel):
    """一个已结束归档的对话轮次，用于"查看历史轮次"列表。"""

    conversation_id: UUID
    persona: Persona
    mood: str | None = Field(default=None, description="结束时生成的拍立得情绪档")
    letter: str | None = Field(default=None, description="结束时生成的拍立得回信正文")
    created_at: str = Field(description="轮次开始时间，ISO 8601")
    ended_at: str = Field(description="轮次结束时间，ISO 8601")


class RoundMessage(BaseModel):
    """历史轮次里的一条消息（只读回看用）。"""

    role: Literal["user", "assistant"]
    content: str
    created_at: str = Field(description="ISO 8601")
