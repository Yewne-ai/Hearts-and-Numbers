"""读取并校验三数问心的版本化六宫语料。"""

import json
from functools import lru_cache
from pathlib import Path

from pydantic import TypeAdapter

from app.domain.reflection.schemas import (
    Palace,
    PalaceCorpusEntry,
    PositionCorpusEntry,
    PositionName,
    Scene,
    SceneCorpusEntry,
    TransitionCorpusEntry,
)

_CORPUS_PATH = (
    Path(__file__).resolve().parents[3]
    / "content"
    / "three-number-reflection"
    / "palaces.v1.json"
)
_POSITION_CORPUS_PATH = _CORPUS_PATH.with_name("positions.v1.json")
_SCENE_CORPUS_PATH = _CORPUS_PATH.with_name("scenarios.draft.v1.json")
_TRANSITION_CORPUS_PATH = _CORPUS_PATH.with_name("transitions.draft.v1.json")
_EXPECTED_PALACES = (
    Palace.DA_AN,
    Palace.LIU_LIAN,
    Palace.SU_XI,
    Palace.CHI_KOU,
    Palace.XIAO_JI,
    Palace.KONG_WANG,
)
_EXPECTED_POSITIONS = (
    PositionName.ORIGIN,
    PositionName.PROCESS,
    PositionName.PRESENT,
)
_CORPUS_ADAPTER = TypeAdapter(list[PalaceCorpusEntry])
_POSITION_CORPUS_ADAPTER = TypeAdapter(list[PositionCorpusEntry])
_SCENE_CORPUS_ADAPTER = TypeAdapter(list[SceneCorpusEntry])
_TRANSITION_CORPUS_ADAPTER = TypeAdapter(list[TransitionCorpusEntry])


@lru_cache(maxsize=1)
def load_palace_corpus() -> tuple[PalaceCorpusEntry, ...]:
    """加载默认语料，并验证六宫数量、索引和顺序。"""

    raw = json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))
    entries = tuple(_CORPUS_ADAPTER.validate_python(raw))

    if len(entries) != len(_EXPECTED_PALACES):
        raise ValueError("六宫语料必须恰好包含六条记录")

    for expected_index, (entry, expected_palace) in enumerate(
        zip(entries, _EXPECTED_PALACES, strict=True)
    ):
        if entry.index != expected_index or entry.label is not expected_palace:
            raise ValueError("六宫语料的索引或顺序与计算引擎不一致")

    return entries


def get_palace_corpus(palace: Palace) -> PalaceCorpusEntry:
    """按宫位读取一条已校验的 v1 语料。"""

    return load_palace_corpus()[_EXPECTED_PALACES.index(palace)]


@lru_cache(maxsize=1)
def load_position_corpus() -> tuple[PositionCorpusEntry, ...]:
    """加载默认位置语料，并验证三个位置的索引和顺序。"""

    raw = json.loads(_POSITION_CORPUS_PATH.read_text(encoding="utf-8"))
    entries = tuple(_POSITION_CORPUS_ADAPTER.validate_python(raw))

    if len(entries) != len(_EXPECTED_POSITIONS):
        raise ValueError("位置语料必须恰好包含三条记录")

    for expected_index, (entry, expected_position) in enumerate(
        zip(entries, _EXPECTED_POSITIONS, strict=True)
    ):
        if entry.index != expected_index or entry.name is not expected_position:
            raise ValueError("位置语料的索引或顺序与计算结果不一致")

    return entries


def get_position_corpus(position: PositionName) -> PositionCorpusEntry:
    """按位置名称读取一条已校验的 v1 语料。"""

    return load_position_corpus()[_EXPECTED_POSITIONS.index(position)]


@lru_cache(maxsize=1)
def load_scene_corpus() -> tuple[SceneCorpusEntry, ...]:
    """加载六个场景技术草案，并确保场景不缺失、不重复。"""

    raw = json.loads(_SCENE_CORPUS_PATH.read_text(encoding="utf-8"))
    entries = tuple(_SCENE_CORPUS_ADAPTER.validate_python(raw))
    if len(entries) != len(Scene) or {entry.id for entry in entries} != set(Scene):
        raise ValueError("场景草案必须恰好覆盖六个固定场景")
    return entries


def get_scene_corpus(scene: Scene) -> SceneCorpusEntry:
    """按场景 ID 读取技术草案。"""

    return next(entry for entry in load_scene_corpus() if entry.id is scene)


@lru_cache(maxsize=1)
def load_transition_corpus() -> tuple[TransitionCorpusEntry, ...]:
    """加载 6×6 全部宫位转折草案，并拒绝缺失或重复组合。"""

    raw = json.loads(_TRANSITION_CORPUS_PATH.read_text(encoding="utf-8"))
    entries = tuple(_TRANSITION_CORPUS_ADAPTER.validate_python(raw))
    combinations = {(entry.from_palace, entry.to_palace) for entry in entries}
    expected = {
        (from_palace, to_palace) for from_palace in Palace for to_palace in Palace
    }
    if len(entries) != 36 or combinations != expected:
        raise ValueError("转折草案必须恰好覆盖 36 种宫位组合")
    return entries


def get_transition_corpus(
    from_palace: Palace, to_palace: Palace
) -> TransitionCorpusEntry:
    """读取两个相邻宫位之间的转折草案。"""

    return next(
        entry
        for entry in load_transition_corpus()
        if entry.from_palace is from_palace and entry.to_palace is to_palace
    )
