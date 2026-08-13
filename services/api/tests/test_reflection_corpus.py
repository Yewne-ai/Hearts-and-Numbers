"""三数问心六宫 v1 语料的完整性与内容冻结测试。"""

from app.domain.reflection import (
    CORPUS_VERSION,
    DRAFT_CORPUS_VERSION,
    METHOD_VERSION,
    Palace,
    PositionName,
    Scene,
    get_palace_corpus,
    get_position_corpus,
    get_scene_corpus,
    get_transition_corpus,
    load_palace_corpus,
    load_position_corpus,
    load_scene_corpus,
    load_transition_corpus,
)

_EXPECTED_CONTENT = {
    Palace.DA_AN: {
        "traditional_keywords": ("稳定", "安定", "守成"),
        "neutral_interpretation": "当前更需要稳定基础，不宜因焦虑强行加速",
        "emotion_lens": ("渴望确定", "控制", "安全感"),
        "action_lens": ("回到事实", "作息", "边界", "已有支持"),
        "forbidden_claims": ("一定成功", "什么都不用做"),
    },
    Palace.LIU_LIAN: {
        "traditional_keywords": ("延迟", "反复", "牵绊"),
        "neutral_interpretation": "问题里可能有尚未结束或反复拉扯的部分",
        "emotion_lens": ("反刍", "等待", "舍不得", "未完成感"),
        "action_lens": ("找出最卡的一环", "为等待设置时间边界"),
        "forbidden_claims": ("永远不会有结果", "被小人缠住"),
    },
    Palace.SU_XI: {
        "traditional_keywords": ("消息", "推动", "转机"),
        "neutral_interpretation": "事情可能正在出现变化，但变化不等于结果",
        "emotion_lens": ("希望", "急迫", "害怕错过"),
        "action_lens": ("做好准备", "验证消息", "避免过早下注"),
        "forbidden_claims": ("马上会复合", "录取已定"),
    },
    Palace.CHI_KOU: {
        "traditional_keywords": ("摩擦", "误解", "言语"),
        "neutral_interpretation": "沟通方式或防御状态可能比事件本身更关键",
        "emotion_lens": ("被冒犯", "委屈", "愤怒", "戒备"),
        "action_lens": ("放慢表达", "确认意图", "避免冲动对抗"),
        "forbidden_claims": ("必有争吵", "对方在害你"),
    },
    Palace.XIAO_JI: {
        "traditional_keywords": ("小进展", "协作", "支持"),
        "neutral_interpretation": "可能有有限但真实的帮助或改善空间",
        "emotion_lens": ("松动", "愿意尝试", "需要支持"),
        "action_lens": ("接受小帮助", "先完成一小步"),
        "forbidden_claims": ("贵人必来", "事情必成"),
    },
    Palace.KONG_WANG: {
        "traditional_keywords": ("信息不足", "落空", "悬置"),
        "neutral_interpretation": "当前可能缺少关键事实，或期待没有现实支撑",
        "emotion_lens": ("失落", "迷茫", "害怕一场空"),
        "action_lens": ("暂停灾难化推演", "补充信息后再决定"),
        "forbidden_claims": ("一切成空", "没有希望"),
    },
}

_EXPECTED_POSITION_CONTENT = {
    PositionName.ORIGIN: {
        "explanation_task": "说明用户为什么会在此刻提出问题",
        "required_elements": ("当前触发点", "问题底色", "可能的情绪需要"),
        "forbidden_content": ("对他人内心的断言",),
    },
    PositionName.PROCESS: {
        "explanation_task": "说明问题如何被关系、环境或行为维持",
        "required_elements": ("互动模式", "阻力", "可观察事实"),
        "forbidden_content": ("虚构未来事件",),
    },
    PositionName.PRESENT: {
        "explanation_task": "说明此刻值得优先处理的部分",
        "required_elements": ("可控因素", "现实小行动", "不确定性"),
        "forbidden_content": ("替用户做最终决定",),
    },
}


def test_palace_corpus_contains_all_six_palaces_in_engine_order() -> None:
    entries = load_palace_corpus()

    assert tuple(entry.label for entry in entries) == tuple(Palace)
    assert tuple(entry.index for entry in entries) == tuple(range(6))
    assert len({entry.id for entry in entries}) == 6


def test_palace_corpus_uses_frozen_versions_and_review_status() -> None:
    for entry in load_palace_corpus():
        assert entry.method_version == METHOD_VERSION
        assert entry.corpus_version == CORPUS_VERSION
        assert entry.review_status == "internal-reviewed"


def test_palace_corpus_matches_approved_product_copy() -> None:
    for palace, expected in _EXPECTED_CONTENT.items():
        entry = get_palace_corpus(palace)

        assert entry.traditional_keywords == expected["traditional_keywords"]
        assert entry.neutral_interpretation == expected["neutral_interpretation"]
        assert entry.emotion_lens == expected["emotion_lens"]
        assert entry.action_lens == expected["action_lens"]
        assert entry.forbidden_claims == expected["forbidden_claims"]


def test_position_corpus_contains_all_positions_in_result_order() -> None:
    entries = load_position_corpus()

    assert tuple(entry.name for entry in entries) == tuple(PositionName)
    assert tuple(entry.index for entry in entries) == tuple(range(3))
    assert len({entry.id for entry in entries}) == 3


def test_position_corpus_uses_frozen_versions_and_review_status() -> None:
    for entry in load_position_corpus():
        assert entry.method_version == METHOD_VERSION
        assert entry.corpus_version == CORPUS_VERSION
        assert entry.review_status == "internal-reviewed"


def test_position_corpus_matches_approved_product_copy() -> None:
    for position, expected in _EXPECTED_POSITION_CONTENT.items():
        entry = get_position_corpus(position)

        assert entry.explanation_task == expected["explanation_task"]
        assert entry.required_elements == expected["required_elements"]
        assert entry.forbidden_content == expected["forbidden_content"]


def test_draft_scene_corpus_covers_all_six_scenes() -> None:
    entries = load_scene_corpus()

    assert {entry.id for entry in entries} == set(Scene)
    assert len(entries) == 6
    for entry in entries:
        assert entry.corpus_version == DRAFT_CORPUS_VERSION
        assert entry.review_status == "draft-unreviewed"
        assert len(entry.question_templates) == 20
        assert len(entry.followup_questions) >= 5
        assert len(entry.micro_actions) >= 5
        assert entry.include_keywords
        assert entry.forbidden_claims
        assert get_scene_corpus(entry.id) == entry


def test_draft_transition_corpus_covers_all_36_combinations() -> None:
    entries = load_transition_corpus()

    assert len(entries) == 36
    assert {(entry.from_palace, entry.to_palace) for entry in entries} == {
        (from_palace, to_palace) for from_palace in Palace for to_palace in Palace
    }
    assert sum(entry.source == "product-document-example" for entry in entries) == 6
    for entry in entries:
        assert entry.corpus_version == DRAFT_CORPUS_VERSION
        assert entry.review_status == "draft-unreviewed"
        assert entry.allowed_interpretation
        assert entry.forbidden_claims
        assert get_transition_corpus(entry.from_palace, entry.to_palace) == entry
