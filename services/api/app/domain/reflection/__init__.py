"""三数问心领域：确定性计算及其结果结构。"""

from app.domain.reflection.calculator import (
    InvalidThreeNumbersError,
    calculate_three_numbers,
)
from app.domain.reflection.fallback import build_fixed_reading
from app.domain.reflection.generator import (
    DeepSeekReflectionGenerator,
    ReflectionExplanationGenerator,
)
from app.domain.reflection.scene_classifier import classify_scene
from app.domain.reflection.service import (
    SceneNotDeterminedError,
    generate_reflection_reading,
)
from app.domain.reflection.corpus import (
    get_palace_corpus,
    get_position_corpus,
    get_scene_corpus,
    get_transition_corpus,
    load_palace_corpus,
    load_position_corpus,
    load_scene_corpus,
    load_transition_corpus,
)
from app.domain.reflection.schemas import (
    CORPUS_VERSION,
    DRAFT_CORPUS_VERSION,
    INPUT_RULE_VERSION,
    METHOD_VERSION,
    Palace,
    PalaceCorpusEntry,
    PositionCorpusEntry,
    PositionName,
    PositionResult,
    ReadingDraft,
    ReadingPositionDraft,
    ReadingTransition,
    ReflectionReading,
    Scene,
    SceneClassification,
    SceneCorpusEntry,
    ThreeNumberResult,
    TransitionCorpusEntry,
)
from app.domain.reflection.verifier import (
    ValidationIssue,
    ValidationReport,
    verify_reading_draft,
)

__all__ = [
    "CORPUS_VERSION",
    "DRAFT_CORPUS_VERSION",
    "DeepSeekReflectionGenerator",
    "INPUT_RULE_VERSION",
    "METHOD_VERSION",
    "InvalidThreeNumbersError",
    "Palace",
    "PalaceCorpusEntry",
    "PositionCorpusEntry",
    "PositionName",
    "PositionResult",
    "ReadingDraft",
    "ReadingPositionDraft",
    "ReadingTransition",
    "ReflectionReading",
    "ReflectionExplanationGenerator",
    "Scene",
    "SceneClassification",
    "SceneCorpusEntry",
    "SceneNotDeterminedError",
    "ThreeNumberResult",
    "TransitionCorpusEntry",
    "ValidationIssue",
    "ValidationReport",
    "calculate_three_numbers",
    "build_fixed_reading",
    "classify_scene",
    "get_palace_corpus",
    "get_position_corpus",
    "get_scene_corpus",
    "get_transition_corpus",
    "generate_reflection_reading",
    "load_palace_corpus",
    "load_position_corpus",
    "load_scene_corpus",
    "load_transition_corpus",
    "verify_reading_draft",
]
