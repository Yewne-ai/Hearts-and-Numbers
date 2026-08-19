"""基于版本化草案关键词的确定性场景识别。"""

from app.domain.reflection.corpus import load_scene_corpus
from app.domain.reflection.schemas import SceneClassification


def classify_scene(question: str) -> SceneClassification:
    """计算每个场景的关键词命中数；同分或无命中时不自动定场景。"""

    normalized = question.strip().casefold()
    scores = {}
    matches = {}

    for entry in load_scene_corpus():
        included = tuple(
            keyword
            for keyword in entry.include_keywords
            if keyword.casefold() in normalized
        )
        excluded = any(
            keyword.casefold() in normalized for keyword in entry.exclude_keywords
        )
        score = 0 if excluded else len(set(included))
        scores[entry.id] = score
        matches[entry.id] = included if score else ()

    highest = max(scores.values(), default=0)
    candidates = tuple(
        scene for scene, score in scores.items() if score == highest and score
    )
    scene = candidates[0] if len(candidates) == 1 else None
    return SceneClassification(
        scene=scene,
        candidates=candidates,
        scores=scores,
        matched_keywords=matches,
    )
