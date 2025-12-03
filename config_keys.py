"""
配置键常量定义
集中管理所有配置键，避免硬编码
"""


class ConfigKeys:
    """配置键常量类"""

    # ========== Plugin 配置 ==========
    PLUGIN_ENABLED = "plugin.enabled"
    PLUGIN_CONFIG_VERSION = "plugin.config_version"

    # ========== General 通用配置 ==========
    GENERAL_DEFAULT_BACKEND = "general.default_backend"
    GENERAL_TIMEOUT = "general.timeout"
    GENERAL_MAX_TEXT_LENGTH = "general.max_text_length"
    GENERAL_USE_REPLYER_REWRITE = "general.use_replyer_rewrite"
    GENERAL_AUDIO_OUTPUT_DIR = "general.audio_output_dir"
    GENERAL_USE_BASE64_AUDIO = "general.use_base64_audio"

    # ========== Components 组件配置 ==========
    COMPONENTS_ACTION_ENABLED = "components.action_enabled"
    COMPONENTS_COMMAND_ENABLED = "components.command_enabled"

    # ========== Probability 概率控制配置 ==========
    PROBABILITY_ENABLED = "probability.enabled"
    PROBABILITY_BASE_PROBABILITY = "probability.base_probability"
    PROBABILITY_KEYWORD_FORCE_TRIGGER = "probability.keyword_force_trigger"
    PROBABILITY_FORCE_KEYWORDS = "probability.force_keywords"

    # ========== AI Voice 配置 ==========
    AI_VOICE_DEFAULT_CHARACTER = "ai_voice.default_character"
    AI_VOICE_ALIAS_MAP = "ai_voice.alias_map"

    # ========== GSV2P 配置 ==========
    GSV2P_API_URL = "gsv2p.api_url"
    GSV2P_API_TOKEN = "gsv2p.api_token"
    GSV2P_DEFAULT_VOICE = "gsv2p.default_voice"
    GSV2P_TIMEOUT = "gsv2p.timeout"
    GSV2P_MODEL = "gsv2p.model"
    GSV2P_RESPONSE_FORMAT = "gsv2p.response_format"
    GSV2P_SPEED = "gsv2p.speed"
    GSV2P_TEXT_LANG = "gsv2p.text_lang"
    GSV2P_EMOTION = "gsv2p.emotion"

    # ========== GPT-SoVITS 配置 ==========
    GPT_SOVITS_SERVER = "gpt_sovits.server"
    GPT_SOVITS_STYLES = "gpt_sovits.styles"

    # ========== Doubao 豆包配置 ==========
    DOUBAO_API_URL = "doubao.api_url"
    DOUBAO_APP_ID = "doubao.app_id"
    DOUBAO_ACCESS_KEY = "doubao.access_key"
    DOUBAO_RESOURCE_ID = "doubao.resource_id"
    DOUBAO_DEFAULT_VOICE = "doubao.default_voice"
    DOUBAO_TIMEOUT = "doubao.timeout"
    DOUBAO_AUDIO_FORMAT = "doubao.audio_format"
    DOUBAO_SAMPLE_RATE = "doubao.sample_rate"
    DOUBAO_BITRATE = "doubao.bitrate"
    DOUBAO_SPEED = "doubao.speed"
    DOUBAO_VOLUME = "doubao.volume"
    DOUBAO_CONTEXT_TEXTS = "doubao.context_texts"
