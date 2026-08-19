"""三数问心确定性计算的领域结构。"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

METHOD_VERSION: Literal["xlr-six-palace-v1"] = "xlr-six-palace-v1"
INPUT_RULE_VERSION: Literal["three-number-1-99-v1"] = "three-number-1-99-v1"
CORPUS_VERSION: Literal["2026-08-v1"] = "2026-08-v1"
DRAFT_CORPUS_VERSION: Literal["2026-08-draft-v1"] = "2026-08-draft-v1"


class Palace(str, Enum):
    """Yewne 六宫三数法 v1 使用的固定六宫。"""

    DA_AN = "大安"
    LIU_LIAN = "留连"
    SU_XI = "速喜"
    CHI_KOU = "赤口"
    XIAO_JI = "小吉"
    KONG_WANG = "空亡"


class PositionName(str, Enum):
    """三次计算结果在产品中的固定位置名称。"""

    ORIGIN = "起势"
    PROCESS = "过程"
    PRESENT = "当下"


class Scene(str, Enum):
    """产品文档冻结的六个三数问心场景。"""

    RELATIONSHIP_UNCERTAINTY = "relationship_uncertainty"
    BREAKUP_BOUNDARY = "breakup_boundary"
    STUDY_PRESSURE = "study_pressure"
    CAREER_CHOICE = "career_choice"
    INTERPERSONAL_CONFLICT = "interpersonal_conflict"
    SELF_DOUBT = "self_doubt"


class PositionResult(BaseModel):
    """一个位置及其对应的宫位。"""

    name: PositionName
    palace: Palace


class ThreeNumberResult(BaseModel):
    """确定性计算结果；不包含任何生成式解释。"""

    method_version: Literal["xlr-six-palace-v1"] = METHOD_VERSION
    input_rule_version: Literal["three-number-1-99-v1"] = INPUT_RULE_VERSION
    numbers: tuple[int, int, int]
    result: tuple[Palace, Palace, Palace]
    positions: tuple[PositionResult, PositionResult, PositionResult]


class PalaceCorpusEntry(BaseModel):
    """一个宫位的审核后 v1 基础语料。"""

    id: str
    index: int = Field(ge=0, le=5)
    method_version: Literal["xlr-six-palace-v1"]
    corpus_version: Literal["2026-08-v1"]
    label: Palace
    traditional_keywords: tuple[str, ...]
    neutral_interpretation: str
    emotion_lens: tuple[str, ...]
    action_lens: tuple[str, ...]
    forbidden_claims: tuple[str, ...]
    review_status: Literal["internal-reviewed"]


class PositionCorpusEntry(BaseModel):
    """一个位置的审核后 v1 解释规则。"""

    id: str
    index: int = Field(ge=0, le=2)
    method_version: Literal["xlr-six-palace-v1"]
    corpus_version: Literal["2026-08-v1"]
    name: PositionName
    explanation_task: str
    required_elements: tuple[str, ...]
    forbidden_content: tuple[str, ...]
    review_status: Literal["internal-reviewed"]


class SceneCorpusEntry(BaseModel):
    """尚待产品审核的场景技术草案。"""

    id: Scene
    corpus_version: Literal["2026-08-draft-v1"]
    label: str
    include_keywords: tuple[str, ...]
    exclude_keywords: tuple[str, ...]
    question_templates: tuple[str, ...]
    fact_check_prompts: tuple[str, ...]
    followup_questions: tuple[str, ...]
    micro_actions: tuple[str, ...]
    forbidden_claims: tuple[str, ...]
    review_status: Literal["draft-unreviewed"]


class TransitionCorpusEntry(BaseModel):
    """两个相邻宫位之间的技术草案转折语料。"""

    id: str
    corpus_version: Literal["2026-08-draft-v1"]
    from_palace: Palace
    to_palace: Palace
    allowed_interpretation: str
    forbidden_claims: tuple[str, ...]
    source: Literal["product-document-example", "technical-draft"]
    review_status: Literal["draft-unreviewed"]


class SceneClassification(BaseModel):
    """确定性场景识别结果；同分时不擅自选择。"""

    scene: Scene | None
    candidates: tuple[Scene, ...]
    scores: dict[Scene, int]
    matched_keywords: dict[Scene, tuple[str, ...]]


class ReadingPositionDraft(BaseModel):
    """生成模型输出的一段位置解释。"""

    model_config = ConfigDict(extra="forbid")

    name: PositionName
    palace: Palace
    interpretation: str = Field(min_length=1, max_length=500)
    grounding_keywords: tuple[str, ...] = Field(min_length=1, max_length=5)


class ReadingDraft(BaseModel):
    """解释生成器必须返回的结构化草稿。"""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=300)
    positions: tuple[ReadingPositionDraft, ReadingPositionDraft, ReadingPositionDraft]
    uncertainty: str = Field(min_length=1, max_length=300)
    reflection_question: str = Field(min_length=1, max_length=300)
    controllable_factors: tuple[str, ...] = Field(min_length=1, max_length=5)
    micro_action: str = Field(min_length=1, max_length=300)
    safety_flags: tuple[str, ...] = ()


class ReadingTransition(BaseModel):
    """服务端固定附加的相邻宫位转折。"""

    corpus_id: str
    from_palace: Palace
    to_palace: Palace
    interpretation: str


class ReflectionReading(ReadingDraft):
    """可交给结果页的完整结构化解释。"""

    method_version: Literal["xlr-six-palace-v1"] = METHOD_VERSION
    input_rule_version: Literal["three-number-1-99-v1"] = INPUT_RULE_VERSION
    corpus_version: Literal["2026-08-v1"] = CORPUS_VERSION
    draft_corpus_version: Literal["2026-08-draft-v1"] = DRAFT_CORPUS_VERSION
    numbers: tuple[int, int, int]
    result: tuple[Palace, Palace, Palace]
    scene: Scene
    scene_label: str
    transitions: tuple[ReadingTransition, ReadingTransition]
    generation_mode: Literal["llm", "fixed-fallback"]
    generator_model_version: str | None = None
    prompt_version: str
    verifier_version: str
    generation_attempts: int = Field(ge=0, le=2)
    fallback_reason: str | None = None
