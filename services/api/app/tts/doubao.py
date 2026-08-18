"""豆包语音合成模型（火山引擎 V3 HTTP Chunked）。

响应格式：换行分隔的 JSON 流，每行 {"code":0,"message":"","data":"<base64_mp3_chunk>"}
"""

import base64
import json
import re

import httpx

from app.core.config import settings
from app.tts.provider import SynthesisResult, TTSError

_ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
_RESOURCE_ID = "seed-tts-2.0"

_DEFAULT_RATE = -8  # range [-50, 100]

# 按人格覆盖 音色 / 资源版本 / 语速。未列出的人格用全局 settings.doubao_tts_voice
# + 默认 _RESOURCE_ID + _DEFAULT_RATE。
#
# [2026-08-03] 两个人格都换成「角色扮演」(ICL_ 前缀)系列,产品点名要的高级音色。
# ⚠️ ICL_ 系列必须配 resource_id="seed-tts-2.0"。用 seed-tts-1.0 会报
#    `app key not found in header or query`——这个报错极具误导性,曾让我们误判成
#    "整个音色分类没开通、需要在火山引擎控制台单独建应用拿 App ID"。实际上现有的
#    DOUBAO_TTS_API_KEY 就够用,只是 resource_id 配错了。用 volc.service_type.10029
#    则报 `resource ID is mismatched with speaker related resource`(这个提示才准确)。
#
# 两个都显式写 pitch=0 和 natural_pauses=False,不是可省略的默认值:
#   pitch 全局是 -2(降调),不写会让线上听感和试音样本不一致;
#   natural_pauses 默认 True 会插 300ms SSML 停顿,试音样本是纯文本没有停顿。
# 试音样本(桌面 优优妮妮高级音色试听0803/)就是按 rate=0 / pitch=0 / 无停顿生成的,
# 产品据此定档,所以线上必须保持同样的参数组合。
_PERSONA_VOICE_OVERRIDES: dict[str, dict[str, object]] = {
    # [2026-08-11] 合并成单一人格后的音色。先沿用妮妮那档（活泼刁蛮）——
    # 它是产品 08-03 试听定过的，而 yewne 的定位"温暖但不甜腻"更接近妮妮
    # 而不是优优的假小子。**这是暂定值，产品重新试听后可能要换。**
    "yewne": {
        "speaker": "ICL_uranus_zh_female_huopodiaoman_tob",
        "resource_id": "seed-tts-2.0",
        "speech_rate": 0,
        "pitch": 0.0,
        "natural_pauses": False,
    },
    # youyou（优优）= 高洞察力·有点毒嘴的老朋友 → 假小子（中性偏飒,配毒舌人设）
    # 历史:少年梓辛(男)→ 京腔侃爷(男,只上线一天)→ 邻家女孩(seed-tts-1.0,rate+6)→ 假小子
    "youyou": {
        "speaker": "ICL_uranus_zh_female_jiaxiaozi_tob",
        "resource_id": "seed-tts-2.0",
        "speech_rate": 0,  # 2026-08-03 产品试听 0 / +5 两档后定 0
        "pitch": 0.0,
        "natural_pauses": False,
    },
    # nini（妮妮）= 温柔知性的小精灵 → 活泼刁蛮
    # 之前没有 override,吃的是全局默认(小何 + rate -8 + pitch -2 + 有停顿)。
    "nini": {
        "speaker": "ICL_uranus_zh_female_huopodiaoman_tob",
        "resource_id": "seed-tts-2.0",
        "speech_rate": 0,
        "pitch": 0.0,
        "natural_pauses": False,
    },
}

_MIN_CLAUSE_LEN = 8  # 逗号两侧从句都要达到此长度才插停顿
_MIN_TEXT_LEN = 20  # 短文本不处理


def _with_natural_pauses(text: str) -> str:
    """在长从句的逗号后插入 SSML break，只在两侧从句都够长时才停顿。"""
    if len(text) < _MIN_TEXT_LEN:
        return text
    parts = re.split(r"([，,])", text)
    out: list[str] = []
    last_clause_len = 0
    for chunk in parts:
        if chunk in ("，", ","):
            out.append(chunk)
        else:
            clause_len = len(chunk.strip())
            if (
                out
                and out[-1] in ("，", ",")
                and last_clause_len >= _MIN_CLAUSE_LEN
                and clause_len >= _MIN_CLAUSE_LEN
            ):
                out.append('<break time="300ms"/>')
            out.append(chunk)
            last_clause_len = clause_len
    return f"<speak>{''.join(out)}</speak>"


class DoubaoTTSProvider:
    """豆包 V3 TTS（seed-tts-2.0）。失败统一抛 TTSError。"""

    async def synthesize(
        self,
        text: str,
        *,
        persona: str | None = None,
    ) -> SynthesisResult:
        stripped = text.strip()
        if not stripped:
            return SynthesisResult(audio=b"")

        override = _PERSONA_VOICE_OVERRIDES.get(persona or "", {})
        voice = str(override.get("speaker", settings.doubao_tts_voice))
        resource_id = str(override.get("resource_id", _RESOURCE_ID))
        speech_rate = int(override.get("speech_rate", _DEFAULT_RATE))
        pitch = float(override.get("pitch", settings.doubao_tts_pitch))
        natural_pauses = bool(override.get("natural_pauses", True))

        payload = {
            "user": {"uid": "yewne"},
            "req_params": {
                "text": _with_natural_pauses(stripped) if natural_pauses else stripped,
                "speaker": voice,
                "audio_params": {
                    "format": "mp3",
                    "sample_rate": 24000,
                    "speech_rate": speech_rate,
                },
                "additions": json.dumps(
                    {
                        "post_process": {"pitch": pitch},
                        "disable_markdown_filter": True,
                        "enable_ssml": True,
                    }
                ),
            },
        }
        headers = {
            "X-Api-Key": settings.doubao_tts_api_key,
            "X-Api-Resource-Id": resource_id,
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                timeout=settings.tts_timeout_seconds
            ) as client:
                response = await client.post(_ENDPOINT, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise TTSError("timeout", f"doubao tts timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise TTSError("network", f"doubao tts network error: {exc}") from exc

        if response.status_code != 200:
            raise TTSError(
                "http_status",
                f"doubao tts {response.status_code}: {response.text[:300]}",
                upstream_status=response.status_code,
            )

        # 响应是换行分隔的 JSON 流，每行 {"code":0,"data":"<base64>"}
        chunks: list[bytes] = []
        for line in response.content.split(b"\n"):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            code = obj.get("code", 0)
            if code not in (0, 20000000) and obj.get("data") is None:
                raise TTSError(
                    "api_error",
                    f"doubao tts error: {obj.get('message', '')} (code {code})",
                )
            if obj.get("data"):
                chunks.append(base64.b64decode(obj["data"]))

        if not chunks:
            raise TTSError("empty_audio", "doubao tts returned no audio chunks")

        return SynthesisResult(audio=b"".join(chunks), content_type="audio/mpeg")
