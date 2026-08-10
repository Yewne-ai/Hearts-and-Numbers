"""应用配置 - 通过环境变量加载"""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


class Settings(BaseSettings):
    """全局配置。所有敏感配置通过 .env 文件加载。"""

    # 环境
    env: Literal["dev", "staging", "prod"] = "dev"
    debug: bool = True

    # 管理后台 token（在 /internal 后台编辑 persona prompt / 采样参数时用，
    # 走 X-Admin-Token 请求头）。留空则 /v1/admin/* 一律返回 503，不会意外暴露。
    admin_token: str = ""

    # CORS —— 允许跨源访问本 API 的站点白名单。
    # [2026-07-29] 原值是 ["*"](任何站点),配合 allow_credentials=True 时 Starlette 会
    # 回显调用方 Origin 并附带 Allow-Credentials,等于给每个源都发了一张带凭证的通行证。
    #
    # 线上 uniai.net.cn 同时提供前端页面和 /v1 API,属于同源,浏览器不做 CORS 检查,
    # 所以收紧这里对线上网页没有影响;Unity 与手机 App 是原生客户端,也不受 CORS 约束。
    # 真正需要放行的只有本地开发(localhost:3000 → 127.0.0.1:8000 端口不同即跨域)。
    #
    # 要新增域名(预览环境 / 测试环境 / 其它子域)时:改 .env 里的 CORS_ORIGINS,逗号分隔,
    # 不要改这里的默认值——默认值只作为没配 .env 时的兜底。带协议头,不要写路径,例如:
    #   CORS_ORIGINS=https://uniai.net.cn,https://staging.uniai.net.cn
    #
    # [2026-07-31] 必须带 NoDecode：pydantic-settings 对 list 类型的环境变量会先做
    # json.loads，逗号分隔的值在 mode="before" 校验器执行**之前**就抛 SettingsError,
    # 服务直接起不来。NoDecode 关掉那次预解析,把原始字符串交给下面的校验器。
    cors_origins: Annotated[list[str], NoDecode] = [
        "https://uniai.net.cn",
        "https://www.uniai.net.cn",  # 带 www 在浏览器眼里是另一个源
        "http://localhost:3000",
        "http://127.0.0.1:3000",  # 与 localhost 同样视为不同源,两个都要写
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_comma_separated_origins(cls, v: object) -> object:
        """允许 .env 里写 `a,b,c`（也兼容 JSON 数组），配置起来更顺手。"""
        if isinstance(v, str):
            text = v.strip()
            if text.startswith("["):
                # 兼容已经按 JSON 数组写好的 .env，别让这次修复反过来把它们弄坏。
                import json

                parsed = json.loads(text)
                return [str(item).strip() for item in parsed]
            return [item.strip() for item in text.split(",") if item.strip()]
        return v

    # 限流 —— [2026-08-01]
    # 额度都是保守估的:按"正常用户远达不到"取值,目的是挡住脚本刷和暴力破解,不是精确配额。
    # 若日志里 rate_limited 出现在真实用户身上,说明估紧了,调大即可(全部可用 .env 覆盖)。
    rate_limit_enabled: bool = True
    rate_limit_chat_per_minute: int = 30  # 一轮对话十几秒,30 已经很宽松
    rate_limit_speech_per_minute: int = 60  # 语音按句调用,比 chat 频繁
    rate_limit_aftercare_per_minute: int = 10  # 一轮对话结束才调一次
    rate_limit_verify_code_per_minute: int = 10  # 配合下面的尝试上限一起挡暴力破解

    # 按身份限流之外再按 IP 兜一层,倍数放大——因为 external_user_id 是客户端自己生成的,
    # 换一个就能绕过按身份的额度。
    #
    # [2026-08-03] 已确认线上 nginx 传的是 X-Real-IP(不是 XFF),deps.client_ip 现在两个
    # 头都认,这层才真正按 IP 生效。倍数从 10 降到 4:10 是"万一所有人共用一个桶别误伤"的
    # 保守值,既然 IP 已经分得开就不需要那么松了。
    #
    # 4 的含义:同一个出口 IP 下允许约 4 个人同时正常使用(家庭/宿舍 WiFi、公司 NAT 都够),
    # 但挡得住单机换 external_user_id 刷额度。⚠️ 学校/大企业这种几百人共用一个出口 IP 的
    # 场景会误伤——日志里 rate_limited 若集中在同一个 IP 且都是真实用户,调大这个值。
    rate_limit_ip_multiplier: int = 4

    # 验证码最多能猜错几次,超过即作废、必须重新发送。
    # 原先完全不限次数:6 位码 100 万种组合、5 分钟有效期、接口又无限流,
    # 可被暴力破解并直接拿到合法 token(账号接管)。
    verify_code_max_attempts: int = 5

    # 数据库持久化；默认关闭，未安装 PostgreSQL 也能运行聊天功能
    persistence_enabled: bool = False
    database_url: str = (
        "postgresql+psycopg://yewne:yewne_dev_password@localhost:5432/yewne_dev"
    )
    database_health_timeout_seconds: float = 2.0

    # Redis（验证码 + 登录 token 存这里）
    redis_url: str = "redis://localhost:6379/0"

    # LLM 供应商选择：dev 默认走 mock；要接真模型时设为 "deepseek" 并填 key
    llm_provider: Literal["mock", "deepseek"] = "mock"
    llm_timeout_seconds: float = 30.0

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-v4-flash"

    # 豆包（LLM 备用，暂未接入）
    doubao_api_key: str = ""

    # STT（语音转文字）
    # 默认 mock，离线/无 key 也能跑 demo；要接真模型改成 "whisper" 并填 WHISPER_API_KEY
    stt_provider: Literal["mock", "whisper"] = "mock"
    stt_timeout_seconds: float = 30.0
    whisper_api_key: str = ""
    whisper_base_url: str = "https://api.siliconflow.cn/v1"
    whisper_model: str = "FunAudioLLM/SenseVoiceSmall"

    # TTS（文字转语音）
    tts_provider: Literal["mock", "minimax", "siliconflow", "doubao"] = "mock"
    tts_timeout_seconds: float = 60.0

    # MiniMax TTS
    minimax_api_key: str = ""
    minimax_group_id: str = ""
    minimax_base_url: str = "https://api.minimaxi.com"
    minimax_tts_model: str = "speech-2.8-turbo"
    minimax_tts_voice_id: str = "female-tianmei"
    minimax_tts_speed: float = 0.92

    # SiliconFlow TTS（复用 WHISPER_API_KEY / WHISPER_BASE_URL）
    siliconflow_tts_model: str = "FunAudioLLM/CosyVoice2-0.5B"
    siliconflow_tts_voice: str = "FunAudioLLM/CosyVoice2-0.5B:anna"
    siliconflow_tts_speed: float = 0.92

    # 豆包 TTS（火山引擎 V3，seed-tts-2.0）
    doubao_tts_api_key: str = ""
    doubao_tts_voice: str = "zh_female_xiaohe_uranus_bigtts"
    doubao_tts_pitch: float = -2.0  # [-12, 12]，负值降调

    # 内容安全
    safety_provider: Literal["mock", "aliyun"] = "mock"
    safety_timeout_seconds: float = 10.0
    aliyun_access_key_id: str = ""
    aliyun_access_key_secret: str = ""
    aliyun_safety_base_url: str = "https://green-cip.cn-hangzhou.aliyuncs.com"
    aliyun_safety_api_version: str = "2022-03-02"
    aliyun_safety_service: str = "ugc_moderation_byllm_pro"
    aliyun_region_id: str = "cn-hangzhou"

    # 短信验证码登录
    # ⚠️ 专用独立的 key,不能复用上面内容安全的 aliyun_access_key_id/secret——
    # 那把是 Ronnie 的账号，没有 dysms 权限；这把短信 key 也没有内容安全权限，
    # 两个用途混用一把 key 会导致其中一个功能静默失效(2026-07-28 踩过账号不对的坑)。
    sms_provider: Literal["mock", "aliyun"] = "mock"
    sms_timeout_seconds: float = 10.0
    aliyun_sms_access_key_id: str = ""
    aliyun_sms_access_key_secret: str = ""
    aliyun_sms_sign_name: str = ""
    aliyun_sms_template_code: str = ""
    aliyun_sms_region_id: str = "cn-hangzhou"
    sms_code_ttl_seconds: int = 300  # 验证码有效期 5 分钟
    sms_resend_cooldown_seconds: int = 60  # 同一手机号防连点
    sms_daily_limit: int = 10  # 单手机号每日最多发送次数

    # 回应模式（v2 分类器 + mode 块）。默认关：打开前需要先定危机流程该做什么。
    # 关闭时链路和 2026-08-03 移除 scene 之后完全一致，不多一次调用。
    response_mode_enabled: bool = False

    # 登录态 token(服务端存储的随机字符串,不是 JWT,方便主动撤销)
    auth_token_ttl_days: int = 30

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()
