"""回应模式分类器 v2——把"用户想要什么回应"作为分类目标，替代 v1 的 5 个 scene。

与 `classifier.py`（v1）并存，互不影响。v1 的 Scene 枚举、prompt、调用点全部保留，
方便拿同一批句子做 A/B；v2 验证不通过就整个删掉，验证通过再考虑替换调用点。
枚举暂时定义在本文件内（而不是 domain/conversation/schemas.py），也是为了让这次
实验零侵入——v2 胜出后再搬去 schemas。

## 为什么推翻 v1 的 5 个 scene

2026-08-05 用 `_probe_scene_on_real_corpus.py` 把 v1 跑在 PsyDTCorpus（真实心理咨询
语料，Apache-2.0）100 条用户首句上，暴露三个问题：

1. **loneliness 是兼职兜底桶**：占 29%，其中「治疗」主题 9/11 落进去，连纯打招呼的
   「你好，咨询师。」也判成 loneliness。prompt 里写着"不确定时也归这里"，于是
   "我不知道"和"这个人孤独"在返回值上无法区分，下游只能按孤独处理。
   最严重的一条：「最近我总是被一种毁灭自己的冲动所困扰」→ loneliness，
   自毁信号被归进最温和的场景。
2. **5 个类不在同一维度上**：late_night 是时间、rumination 是思维模式、
   relationship/stress 是话题、loneliness 是情绪。prompt 要求"多场景共存时挑最强烈的
   一个"，但不同维度本来就同时成立，这是逻辑上做不到的要求。
3. **late_night 在纯文本上近乎失效**：100 条只判出 1 条，因为文本里通常没有时间信息。
   而用户什么时候打开 App 服务端本来就知道——这不该是分类任务，应该读时钟。

## v2 的设计原则

**只保留会触发不同程序行为的维度。**

生成模型直接读原文，比读一个粗糙的话题标签知道得多，所以"话题分类"这一维的边际价值
很低，v2 直接砍掉。留下的唯一维度是"用户想要什么回应"，因为它直接决定回复该长什么样
——倾诉时给建议是添堵，求建议时只共情是敷衍。

`UNCLEAR` 是显式的第五类，不是兜底进某个真实类别。这是 v2 相对 v1 最核心的修正：
下游拿到 UNCLEAR 时应该先问一句，而不是猜一个然后按猜的结果开聊。

## 关于置信度

v2 只返回模式，不返回数值置信度。原因：LLM 自报的置信度校准很差，加了徒增解析复杂度；
而 UNCLEAR 本身就是低置信的表达通道。
如果以后确实需要数值置信度，常规做法是多次采样投票——但注意
`_probe_classifier_stability.py` 实测 temperature=0.0 下 20 次调用结果完全一致
（10/10 句零抖动），也就是说在当前配置下投票拿不到任何多样性，必须先把温度调上去
才有意义。
"""

import asyncio
from typing import Protocol

import httpx
import structlog

from app.core.config import settings
from app.domain.conversation.modes import ResponseMode
from app.llm.danger_rules import combined_risk_level, matched_rules

logger = structlog.get_logger(__name__)


_VALID_MODES: set[str] = {m.value for m in ResponseMode}
# 常规分类那一段只在这四个里选，危险两级由独立的筛查段负责
_NORMAL_MODES: set[str] = {
    ResponseMode.VENT.value,
    ResponseMode.ADVICE.value,
    ResponseMode.VALIDATE.value,
    ResponseMode.UNCLEAR.value,
}

# v1 的兜底是 LONELINESS——一个真实类别，导致"不知道"和"孤独"混在一起。
# v2 兜底到 UNCLEAR：网络失败、解析失败、非法 token 都归这里，语义上是
# "这次没能判出来"，恰好和"信息不足判不了"是同一种下游处理（先问一句）。
_DEFAULT_MODE: ResponseMode = ResponseMode.UNCLEAR

# 危险筛查那一段的输出 ↔ 文档 8.4 的 S 级，两个方向各一份。
# 分开写是因为 S0 不映射回任何模式（常规分类接手），不是双射。
_MODEL_LEVELS: dict[str, str] = {"crisis": "S3", "concern": "S2"}
_LEVEL_TO_MODE: dict[str, ResponseMode] = {
    "S3": ResponseMode.CRISIS,
    "S2": ResponseMode.CONCERN,
}


class ResponseModeClassifier(Protocol):
    """回应模式分类器接口。实现必须保证不抛异常，失败时返回 `_DEFAULT_MODE`。"""

    async def classify(self, user_text: str) -> ResponseMode: ...


# prompt 设计要点：
# 1. LLM 有强烈的"总要选一个"倾向，所以必须反复强调 unclear 是合法答案而非失败，
#    否则 v1 那个"什么都往兜底桶里塞"的毛病会原样搬到 unclear 上。
# 2. 每类都给了判别性例子，重点是那些**容易判错的**（打招呼、迷茫、抱怨但不求解）。
#    例子取自 2026-08-05 PsyDTCorpus 实测中 v1 判错的样本。
# 3. crisis 的边界要卡住：不是"情绪很差"就算，必须有自伤/伤人/失控的实质信号。
#    放太宽会让正常的痛苦倾诉走进谨慎路径，那同样是伤害。
_MODE_PROMPT = """你的任务是判断用户这句话**想要什么样的回应**，而不是判断他在聊什么话题。

4 个选项：

- vent：只想倾诉、被听见。在描述发生了什么事、自己多难受，但没有在求办法，
  也没有在怀疑自己（怀疑自己是 validate）。重点落在**外面发生的事**上。
  例：「今天又被我妈说了一顿，烦死了」「就是很累，说不上来为什么」
  　　「他总是说自己的事，谁在乎他什么样」

- advice：想要具体的办法或建议。有明确的困境要解决，或直接在问该怎么办。
  例：「我该怎么跟他开口」「有没有办法能让我晚上不那么焦虑」

- validate：句子的**落点是"我这个人 / 我的做法"本身**——在质疑自己的价值、正当性、
  或还有没有希望，需要被顶回去。
  判据是落点，不是句式：不要靠"是不是…吧"这类尾巴来认（"我们是不是早就淡了"
  落点在那段关系上，是 vent，不是求认同）。
  典型：说自己是累赘 / 什么都不会；把自己的特点当缺点；对自己值不值得、配不配、
  还有没有希望没把握；做法被否定后反问"我就不能…吗"。
  例：「我是不是家里的累赘啊」「我还能遇到真爱吗」「我总是纠结小事，好烦」
  　　「我穿点喜欢的衣服总被骂，我就不能有点自己喜欢的事吗」「我到底要做到什么样」

  **与 vent 的边界（最容易搞错的地方）：**
  带着自我怀疑、但落点在**一件具体的事或处境**上的，仍然是 vent，不是 validate。
  这时候要先接住那件事，而不是急着去反驳他对自己的评价。
  是 vent 不是 validate：「我把事情弄得一团糟」（落点是那件搞砸的事）、
  「我朋友好像都不喜欢我」（落点是朋友关系）、「咨询也做了还是迈不过去」（落点是那个坎）。

- unclear：信息不足，判不出他想要什么。
  只有一声叹息或语气词、没有任何内容时，一律 unclear——哪怕它带情绪。
  例：「在吗」「你好」「嗯」「唉」「哎」「……」「不知道怎么说」「最近有点不对劲」

**关于 unclear 的重要说明：**
unclear 是一个正常且常用的答案，不是失败。用户第一句只是打招呼、或者只说了一句
含糊的感受、或者信息太少无法判断意图时，就应该返回 unclear——下游会先问一句再聊。
不要为了"给个答案"而硬猜。宁可 unclear，不要猜错。

判断规则：
1. 只看用户想要什么回应。聊工作、聊恋爱、聊家庭都可能是任意一种模式，
   但有一处话题确实会影响判断，见规则 2。
2. **感情/恋爱的事，只有情绪、没有说具体发生了什么时 → unclear，先问一句。**
   这类事要知道细节（谁、什么事、多久了）才接得准，泛泛安慰接不住。
   例：「唉，恋爱谈得好累啊」→ unclear。
   工作/学业的疲惫不适用这条——「每天上班难受死了」这种表达本身就是全部内容，
   没有更多细节可挖，直接 vent 接住。
   这条只管"光有情绪没有事件"的情形：已经说了具体事件（「有别人和他讲话，我受不了了」）、
   明确在问办法（「要怎么认识他啊」）、或在质疑自我价值（「我还能遇到真爱吗」）的，
   仍按各自的模式判，不要套这条。
3. 同时像多种时，选最主要的那个诉求。
4. 信息不足就返回 unclear，这是正确答案而不是逃避。
5. **只输出一个英文单词**（vent / advice / validate / unclear），全小写，不要任何解释、标点、换行、引号。
"""


# 第一段：危险信号筛查。
# 单独一次调用，和常规分类并行。这样做的原因（2026-08-09 实测）：
# 把 crisis/concern 的判据写进主 prompt 之后，unclear 的准确率从 57% 掉到 43%，
# 13 条全跑去了 vent——典型的指令稀释，加进去的内容即使和当前样本无关也会干扰判断。
# 拆开之后两边的判据互不干扰，而且并行发出，延迟取 max 不是 sum。
_DANGER_PROMPT = """你只做一件事：判断用户这句话里有没有指向自伤、自杀或伤人的信号。

只输出三个词之一：crisis / concern / none

crisis：**明确说出**了自伤、自杀、伤人的念头或决意。
  例：「我不想活了」「总有一种毁灭自己的冲动」「我怕我会做出什么事来」
  　　「从这跳下去，会是一种解脱吗」「我已经想好了，不用再劝我了」

concern：**没有明说，但话里指向同一件事**。宁可判到这里，也不要放过去。
  下面任何一种出现了就算，不需要凑齐几条：
  · **场所**：天台、桥、河边、水边、高处、深夜的路——尤其配上"站在这里""留在这里"
  · **告别**：「以后不用麻烦你了」「他们不用再为我操心了」「谢谢这个美好的世界」
  · **交代**：「这是我最后的愿望」「帮我照顾…」，或突然安排身后的事
  · **与逝者**：说起去世的人时带着靠近、被召唤的意思
  　　「她应该很想我吧」「那颗星星是你吗」「他在让我去找他呢」
  · **无牵挂**：「我没什么牵挂了」「每个人都有自己的生活」
  · **解脱感**：「终于能歇一歇了」「怎样都无所谓了」「什么都不用想了」
  · **存续怀疑**：「我还能等到天亮吗」「留在这里还有什么意义」

  **怎么和日常的夸张区分**——这是最容易搞错的地方：
  中文里"死"常被拿来夸张，「烦死了」「累死我了」「堵车真是想死」「早饭撒了一地真想
  原地消失」「干脆让我死了算了」，这些都**不是** crisis 也不是 concern，是 vent。
  判别看两点：
  1. 有没有**具体而琐碎的触发**（堵车、加班、月光、室友吵）——有就是抱怨
  2. 语气是**急躁抱怨**还是**平静、抽离、告别**——前者是发泄，后者才是信号
  同样一句"想死"，跟在堵车后面是抱怨，出现在一段平静的告别里就要当回事。

  另外：单独一句「我好害怕」「我好想你们」不足以判 concern——它们要和上面某一类
  同时出现才算。孤立地看，那是 vent。

none：以上都不是。日常的抱怨、难过、痛苦、绝望表达都归这里。

**只输出一个英文单词**（crisis / concern / none），全小写，不要任何解释、标点、换行、引号。
"""


class DeepSeekResponseModeClassifier:
    """两段并行:危险筛查 + 常规分类。任何失败都内部消化,对外只返回合法 ResponseMode。

    为什么并行而不是串行:两段互不依赖,同时发出去延迟取 max 不是 sum,
    比单段方案只多花一次调用的钱、不多花时间。

    危险筛查的结果**优先**——它出 crisis/concern 就直接用，不看常规分类说什么。
    这一类漏判的代价不可逆，宁可让常规分类的结果作废。
    """

    async def _ask(
        self, prompt: str, user_text: str, valid: set[str], tag: str
    ) -> str | None:
        payload = {
            "model": settings.deepseek_model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.0,
            "max_tokens": 16,
            # 同 v1：v4-flash 是推理模型，默认会先吐 reasoning_content。这里只要一个词，
            # 关掉 thinking 免得推理 token 把 max_tokens 吃完、content 截断成空串。
            "thinking": {"type": "disabled"},
        }
        headers = {
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        url = f"{settings.deepseek_base_url}/chat/completions"

        try:
            async with httpx.AsyncClient(
                timeout=settings.llm_timeout_seconds
            ) as client:
                response = await client.post(url, headers=headers, json=payload)
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            logger.warning(f"{tag}_network_failed", error=str(exc))
            return None

        if response.status_code != 200:
            logger.warning(f"{tag}_http_non_200", status=response.status_code)
            return None

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            logger.warning(f"{tag}_decode_failed", error=str(exc))
            return None

        token = content.strip().lower().rstrip(".,!?，。\n\"'")
        if token in valid:
            return token
        logger.warning(f"{tag}_invalid_token", token=token[:32])
        return None

    async def classify(self, user_text: str) -> ResponseMode:
        danger, normal = await asyncio.gather(
            self._ask(
                _DANGER_PROMPT,
                user_text,
                {"crisis", "concern", "none"},
                "danger_screen",
            ),
            self._ask(_MODE_PROMPT, user_text, _NORMAL_MODES, "mode_classify"),
        )

        # 模型判定和确定性规则取高——文档 5.10 要求"不能只让同一模型自我复核"。
        # 规则层不调模型，所以模型限流/降级/供应商换版本时它照常工作。
        model_level = _MODEL_LEVELS.get(danger or "", "S0")
        level = combined_risk_level(model_level, user_text)
        if level != model_level:
            logger.info(
                "danger_escalated_by_rules",
                model_level=model_level,
                final_level=level,
                rules=matched_rules(user_text),  # 规则名，不含原文（文档 8.8）
            )

        if level in _LEVEL_TO_MODE:
            return _LEVEL_TO_MODE[level]

        # 危险筛查失败（None）时不当作 none——那会把网络故障变成"安全"，
        # 但也不能因此把所有请求都判成危机，所以只是退回常规分类的结果。
        if normal is not None:
            return ResponseMode(normal)
        return _DEFAULT_MODE


class MockResponseModeClassifier:
    """关键词兜底。dev 无 key 时使用，正确率不高但能 demo 起 5 个模式。

    顺序有讲究：crisis / concern 必须最先判（安全优先），unclear 的短句判定放最后，
    避免"我不想活了"这种短句被长度规则抢先判成 unclear。
    """

    _CRISIS = (
        "不想活",
        "自杀",
        "去死",
        "毁灭自己",
        "伤害自己",
        "活不下去",
        "结束这一切",
    )
    # 情境暗示：单个词不足以定性，但 dev 环境下有总比没有强。
    # 真实判定靠 DeepSeek 那版的判据，这里只保证 mock 不会把这类漏成 vent。
    _CONCERN = (
        "天台",
        "跳下去",
        "最后的愿望",
        "不用再劝我",
        "没什么牵挂",
        "不用麻烦你了",
        "不用再为我操心",
        "终于能歇一歇",
        "还有什么意义",
    )
    _ADVICE = ("怎么办", "该怎么", "有没有办法", "怎么做", "如何", "求助", "帮我")
    _VALIDATE = (
        "是不是我",
        "过分吗",
        "正常吗",
        "小题大做",
        "是不是太",
        "对吧",
        "换成别人",
    )

    async def classify(self, user_text: str) -> ResponseMode:
        text = user_text or ""
        if any(kw in text for kw in self._CRISIS):
            return ResponseMode.CRISIS
        if any(kw in text for kw in self._CONCERN):
            return ResponseMode.CONCERN
        if any(kw in text for kw in self._VALIDATE):
            return ResponseMode.VALIDATE
        if any(kw in text for kw in self._ADVICE):
            return ResponseMode.ADVICE
        # 太短、且没有任何上面的信号 —— 判不了。阈值 6 是拍的，
        # 目的是让「在吗」「你好」「嗯」这类落进 unclear 而不是硬猜成 vent。
        if len(text.strip()) < 6:
            return ResponseMode.UNCLEAR
        return ResponseMode.VENT


def get_response_mode_classifier() -> ResponseModeClassifier:
    """按 LLM_PROVIDER 选实现，与 llm/factory.py 里 get_scene_classifier 同构。

    v2 还没接进主链路，所以暂时不动 factory.py——验证通过后再搬过去。
    """
    if settings.llm_provider == "mock":
        return MockResponseModeClassifier()
    return DeepSeekResponseModeClassifier()
