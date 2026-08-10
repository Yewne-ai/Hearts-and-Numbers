"""确定性危险规则层——对齐产品文档 5.10。

文档要求「校验至少包含确定性 Schema/规则检查，不能只让同一模型"自我复核"」。
这套测试要证明的正是**独立性**：模型整个挂掉时，规则仍然能把危险信号顶上去。

不打网络：模型那一段用 stub 替掉。
"""

import pytest

from app.llm import classifier_v2
from app.domain.conversation.modes import ResponseMode
from app.llm.danger_rules import (
    combined_risk_level,
    matched_rules,
    rule_risk_level,
)

# 取自产品第二批「情境暗示的危机表达」，规则应当抓到的
SITUATIONAL = [
    "天台的风好大啊，站在这里什么都不用想了",
    "河边的晚风好舒服啊，一直留在这里也挺好的",
    "以后不用麻烦你了，再也不用了",
    "这是我最后的愿望，谢谢你愿意听",
    "我已经想好了，不用再劝我了",
    "每个人都有自己的生活，我没什么牵挂了",
    "终于能歇一歇了",
    "他们不用再为我操心了",
    "他在让我去找他呢",
    "谢谢这个美好的世界，我爱你们",
]

# 取自产品第二批「听起来像危机、其实不是」。规则**必须**全部放过——
# 这类靠上下文才分得清，规则做不到，误伤的代价是把正常倾诉当病人对待。
HYPERBOLE = [
    "烦死了，世界毁灭吧",
    "我要疯了",
    "累死我了，加班真的扛不住了",
    "这日子没法过了！",
    "我真的想死的心都有了",
    "室友天天打游戏，吵得我真的崩溃了",
    "工资又月光了，我人没了啊",
    "这早高峰堵了一个多小时，真是想死",
    "早饭撒了一地，真想原地消失",
    "怎么还有这么多事情要搞，干脆让我死了算了",
    "看到他过得这么好我真的难受死了",
    "所有人都下地狱去吧",
]


class TestRulesAlone:
    @pytest.mark.parametrize("text", SITUATIONAL)
    def test_situational_signals_are_caught(self, text: str):
        assert rule_risk_level(text) in ("S2", "S3"), text

    @pytest.mark.parametrize("text", HYPERBOLE)
    def test_hyperbole_never_escalates(self, text: str):
        """日常夸张一条都不能命中。这条红了就是规则写宽了，
        代价是正常倾诉的人被当成危机处理。"""
        assert rule_risk_level(text) == "S0", f"误伤: {text} ← {matched_rules(text)}"

    def test_explicit_expression_is_s3(self):
        assert rule_risk_level("我不想活了") == "S3"

    def test_place_alone_is_not_enough(self):
        """单说场所不算——「天台」可能只是在说风景。必须配上停留/跳下去这类。"""
        assert rule_risk_level("我们公司天台可以看到江景") == "S0"
        assert rule_risk_level("周末去河边野餐了") == "S0"

    def test_matched_rules_returns_names_not_quotes(self):
        """文档 8.8：RISK_EVENT 记 decision_reason_code，不留原文引用。"""
        text = "天台的风好大啊，站在这里什么都不用想了"
        names = matched_rules(text)
        assert names
        for name in names:
            assert name not in text
            assert "天台" not in name


class TestCombination:
    def test_takes_the_higher_level(self):
        assert combined_risk_level("S0", "终于能歇一歇了") == "S2"
        assert combined_risk_level("S3", "今天天气不错") == "S3"

    def test_rules_can_escalate_a_silent_model(self):
        """模型说没事、规则说有事 → 升级。这就是独立校验的意义。"""
        assert combined_risk_level("S0", "我已经想好了，不用再劝我了") == "S2"

    def test_model_can_catch_what_rules_miss(self):
        """反过来也成立：规则只覆盖固定措辞，其余靠模型。"""
        assert combined_risk_level("S2", "池子里的鱼好自由啊，我也能这样吗") == "S2"

    def test_unknown_level_never_crashes(self):
        assert combined_risk_level("", "今天天气不错") == "S0"


class TestIndependenceFromModel:
    """文档 5.10 的核心：模型整个失效时，这条链路不能跟着失效。"""

    @pytest.fixture
    def dead_model(self, monkeypatch: pytest.MonkeyPatch):
        """两段模型调用全部返回 None（网络失败 / 非法 token / 非 200）。"""

        async def _fail(self, prompt, user_text, valid, tag):
            return None

        monkeypatch.setattr(classifier_v2.DeepSeekResponseModeClassifier, "_ask", _fail)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text", SITUATIONAL)
    async def test_situational_still_escalates_when_model_is_down(
        self, dead_model, text: str
    ):
        clf = classifier_v2.DeepSeekResponseModeClassifier()
        assert await clf.classify(text) in (
            ResponseMode.CONCERN,
            ResponseMode.CRISIS,
        ), text

    @pytest.mark.asyncio
    async def test_model_down_on_ordinary_text_falls_back_to_default(self, dead_model):
        """规则没命中时仍是老行为：退回默认，不因为模型挂了就报警。"""
        clf = classifier_v2.DeepSeekResponseModeClassifier()
        assert await clf.classify("今天路上看到一只很胖的猫") is ResponseMode.UNCLEAR

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text", HYPERBOLE)
    async def test_model_down_does_not_turn_hyperbole_into_crisis(
        self, dead_model, text: str
    ):
        """模型挂了也不能开始误伤——否则一次限流就把所有抱怨都当成危机。"""
        clf = classifier_v2.DeepSeekResponseModeClassifier()
        assert await clf.classify(text) not in (
            ResponseMode.CONCERN,
            ResponseMode.CRISIS,
        ), text
