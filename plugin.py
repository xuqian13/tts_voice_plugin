"""统一TTS语音合成插件（MaiBot SDK 2.x 版本）

支持七种后端：AI Voice (MaiCore 内置) / GSV2P (云 API) / GPT-SoVITS (本地服务) /
豆包语音 (云 API) / CosyVoice (ModelScope Gradio) / 小米 MiMo (云 API) / minimax (云 API)。

本文件已迁移到新版 ``maibot_sdk`` 风格：
- 使用 :class:`MaiBotPlugin` 作为基类。
- 使用 ``@Action`` / ``@Command`` 装饰器声明组件。
- 通过 ``self.ctx`` 访问发送能力 / LLM 能力 / 日志。
- 通过 Pydantic ``PluginConfigBase`` 声明配置 Schema。

Version: 3.3.0
Author: 靓仔（原作者）/ MaiBot 适配
"""

import sys

sys.dont_write_bytecode = True

import asyncio
import logging
import random
from typing import Any, Callable, Dict, List, Optional, Tuple

import aiohttp

from maibot_sdk import Action, Command, Field, MaiBotPlugin, PluginConfigBase
from maibot_sdk.types import ActivationType, ChatMode

from .backends import TTSBackendRegistry, TTSResult
from .backends.ai_voice import AI_VOICE_ALIAS_MAP
from .backends.doubao import DOUBAO_EMOTION_MAP
from .config_keys import ConfigKeys
from .utils.text import TTSTextUtils

logger = logging.getLogger("plugin.tts_voice_plugin")

# 有效后端列表
VALID_BACKENDS: List[str] = ["ai_voice", "gsv2p", "gpt_sovits", "doubao", "cosyvoice", "mimo", "minimax"]


# ─── Pydantic 配置模型 ────────────────────────────────────────────────────────


class PluginSectionConfig(PluginConfigBase):
    """插件基础配置。"""

    __ui_label__ = "插件"
    __ui_icon__ = "package"
    __ui_order__ = 0

    enabled: bool = Field(default=True, description="是否启用插件")
    config_version: str = Field(default="3.3.0", description="配置版本")


class GeneralConfig(PluginConfigBase):
    """通用设置。"""

    __ui_label__ = "通用"
    __ui_icon__ = "settings"
    __ui_order__ = 1

    default_backend: str = Field(
        default="cosyvoice",
        description="默认TTS后端 (ai_voice/gsv2p/gpt_sovits/doubao/cosyvoice/mimo/minimax)",
    )
    timeout: int = Field(default=60, description="请求超时时间（秒）")
    max_text_length: int = Field(
        default=200,
        description="最大文本长度（用于在调用 LLM 时注入到 prompt，让 LLM 直接生成符合长度的回复）",
    )
    use_replyer_rewrite: bool = Field(default=True, description="是否使用 LLM 润色语音内容")
    audio_output_dir: str = Field(default="", description="音频文件输出目录，留空使用项目根目录")
    use_base64_audio: bool = Field(default=True, description="是否使用 base64 编码发送音频")
    split_sentences: bool = Field(default=True, description="是否分段发送（按句切分，每句一条语音）")
    split_delay: float = Field(default=0.3, description="分段发送时每条语音之间的延迟（秒）")
    send_error_messages: bool = Field(default=True, description="是否在语音合成失败时向用户发送错误提示")


class ComponentsConfig(PluginConfigBase):
    """组件启用控制。"""

    __ui_label__ = "组件"
    __ui_icon__ = "blocks"
    __ui_order__ = 2

    action_enabled: bool = Field(default=True, description="是否启用 Action 组件（LLM 自主触发）")
    command_enabled: bool = Field(default=True, description="是否启用 Command 组件（用户手动 /tts）")


class ProbabilityConfig(PluginConfigBase):
    """概率控制。"""

    __ui_label__ = "概率"
    __ui_icon__ = "dice"
    __ui_order__ = 3

    enabled: bool = Field(default=False, description="是否启用概率控制")
    base_probability: float = Field(default=1.0, description="基础触发概率（0.0~1.0）")
    keyword_force_trigger: bool = Field(default=True, description="是否在命中关键词时强制触发")
    force_keywords: List[str] = Field(
        default_factory=lambda: ["一定要用语音", "必须语音", "语音回复我", "务必用语音"],
        description="强制触发关键词",
    )


class AIVoiceConfig(PluginConfigBase):
    """AI Voice 后端配置。"""

    __ui_label__ = "AI Voice"
    __ui_icon__ = "mic"
    __ui_order__ = 10

    default_character: str = Field(default="邻家小妹", description="默认音色名称")


class GSV2PConfig(PluginConfigBase):
    """GSV2P 后端配置。"""

    __ui_label__ = "GSV2P"
    __ui_icon__ = "cloud"
    __ui_order__ = 11

    api_url: str = Field(default="https://gsv2p.acgnai.top/v1/audio/speech", description="API 地址")
    api_token: str = Field(default="", description="API 认证 Token")
    default_voice: str = Field(default="原神-中文-派蒙_ZH", description="默认音色")
    timeout: int = Field(default=120, description="API 请求超时（秒）")
    model: str = Field(default="tts-v4", description="TTS 模型")
    response_format: str = Field(default="wav", description="音频格式")
    speed: float = Field(default=1.0, description="语音速度")


class GPTSovitsStyle(PluginConfigBase):
    """GPT-SoVITS 单个风格配置。"""

    name: str = Field(default="default", description="风格名称")
    refer_wav: str = Field(default="", description="参考音频路径")
    prompt_text: str = Field(default="", description="参考文本")
    prompt_language: str = Field(default="zh", description="参考语言")
    gpt_weights: str = Field(default="", description="GPT 模型权重路径（可选）")
    sovits_weights: str = Field(default="", description="SoVITS 模型权重路径（可选）")


class GPTSovitsConfig(PluginConfigBase):
    """GPT-SoVITS 后端配置。"""

    __ui_label__ = "GPT-SoVITS"
    __ui_icon__ = "server"
    __ui_order__ = 12

    server: str = Field(default="http://127.0.0.1:9880", description="GPT-SoVITS 服务地址")
    styles: List[GPTSovitsStyle] = Field(
        default_factory=lambda: [GPTSovitsStyle()],
        description="风格配置列表",
    )


class DoubaoConfig(PluginConfigBase):
    """豆包语音后端配置。"""

    __ui_label__ = "豆包"
    __ui_icon__ = "cloud"
    __ui_order__ = 13

    api_url: str = Field(
        default="https://openspeech.bytedance.com/api/v3/tts/unidirectional",
        description="豆包语音 API 地址",
    )
    app_id: str = Field(default="", description="豆包 APP ID")
    access_key: str = Field(default="", description="豆包 Access Key")
    resource_id: str = Field(default="seed-tts-2.0", description="豆包 Resource ID")
    default_voice: str = Field(default="zh_female_vv_uranus_bigtts", description="默认音色")
    timeout: int = Field(default=60, description="API 请求超时（秒）")
    audio_format: str = Field(default="wav", description="音频格式")
    sample_rate: int = Field(default=24000, description="采样率")
    bitrate: int = Field(default=128000, description="比特率")
    speed: float = Field(default=0.0, description="语音速度（0 或负值表示不设置）")
    volume: float = Field(default=0.0, description="音量（0 或负值表示不设置）")
    context_texts: List[str] = Field(
        default_factory=list,
        description="上下文辅助文本（留空不发送）",
    )


class CosyVoiceConfig(PluginConfigBase):
    """CosyVoice 后端配置。"""

    __ui_label__ = "CosyVoice"
    __ui_icon__ = "cloud"
    __ui_order__ = 14

    gradio_url: str = Field(
        default="https://funaudiollm-fun-cosyvoice3-0-5b.ms.show/",
        description="Gradio API 地址",
    )
    default_mode: str = Field(default="3s极速复刻", description="推理模式")
    default_instruct: str = Field(
        default="You are a helpful assistant. 请用广东话表达。<|endofprompt|>",
        description="默认指令（自然语言控制模式）",
    )
    reference_audio: str = Field(default="", description="参考音频路径（3s极速复刻模式）")
    prompt_text: str = Field(default="", description="提示文本（3s极速复刻模式）")
    timeout: int = Field(default=300, description="API 请求超时（秒）")
    audio_format: str = Field(default="wav", description="音频格式")


class MiMoConfig(PluginConfigBase):
    """小米 MiMo 后端配置。"""

    __ui_label__ = "小米 MiMo"
    __ui_icon__ = "cloud"
    __ui_order__ = 15

    api_url: str = Field(
        default="https://api.xiaomimimo.com/v1/chat/completions",
        description="小米 MiMo TTS API 地址",
    )
    api_key: str = Field(default="", description="小米 MiMo API Key")
    model: str = Field(default="mimo-v2-tts", description="TTS 模型")
    default_voice: str = Field(default="mimo_default", description="默认音色")
    audio_format: str = Field(default="wav", description="音频格式")
    timeout: int = Field(default=60, description="API 请求超时（秒）")
    user_context: str = Field(default="", description="可选的 user 角色上下文文本（留空不发送）")


class MiniMaxConfig(PluginConfigBase):
    """minimax 后端配置。"""

    __ui_label__ = "minimax"
    __ui_icon__ = "cloud"
    __ui_order__ = 16

    api_url: str = Field(
        default="https://api-bj.minimaxi.com/v1/t2a_v2",
        description="minimax TTS API 地址",
    )
    api_key: str = Field(default="", description="minimax API Key（在 minimax 开放平台申请）")
    model: str = Field(
        default="speech-2.6-hd",
        description="TTS 模型: speech-2.8-hd/speech-2.8-turbo/speech-2.6-hd/speech-2.6-turbo/speech-02-hd/speech-02-turbo/speech-01-hd/speech-01-turbo",
    )
    default_voice: str = Field(
        default="male-qn-qingse",
        description="默认音色 ID（可在此修改为其他系统音色、复刻音色或自定义音色）",
    )
    timeout: int = Field(default=30, description="API 请求超时（秒）")
    audio_format: str = Field(default="mp3", description="音频格式: mp3/pcm/flac/wav")
    sample_rate: int = Field(default=32000, description="采样率")
    bitrate: int = Field(default=128000, description="比特率")
    speed: float = Field(default=1.0, description="语音速度（0.5~2.0，1.0=正常）")
    volume: float = Field(default=1.0, description="音量（0~10，1.0=正常）")
    pitch: int = Field(default=0, description="音调（-12~12，0=正常）")
    channel: int = Field(default=1, description="声道数: 1=单声道, 2=立体声")


class TTSPluginConfig(PluginConfigBase):
    """TTS 插件总配置。"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    components: ComponentsConfig = Field(default_factory=ComponentsConfig)
    probability: ProbabilityConfig = Field(default_factory=ProbabilityConfig)
    ai_voice: AIVoiceConfig = Field(default_factory=AIVoiceConfig)
    gsv2p: GSV2PConfig = Field(default_factory=GSV2PConfig)
    gpt_sovits: GPTSovitsConfig = Field(default_factory=GPTSovitsConfig)
    doubao: DoubaoConfig = Field(default_factory=DoubaoConfig)
    cosyvoice: CosyVoiceConfig = Field(default_factory=CosyVoiceConfig)
    mimo: MiMoConfig = Field(default_factory=MiMoConfig)
    minimax: MiniMaxConfig = Field(default_factory=MiniMaxConfig)


# ─── 插件主体 ────────────────────────────────────────────────────────────────


class UnifiedTTSPlugin(MaiBotPlugin):
    """统一 TTS 语音合成插件（MaiBot SDK 2.x 版）。

    Action 由 LLM 自主决定是否使用语音回复；
    Command 由用户手动通过 ``/tts``、``/voice``、``/doubao`` 等命令触发。
    """

    config_model = TTSPluginConfig

    async def on_load(self) -> None:
        """插件加载完成回调：根据配置启停各组件。"""

        # 根据 components 配置启停 Action / Command 组件
        # 注意：@Action 装饰器在新 SDK 内部被注册为 Tool 类型
        if not self.config.components.action_enabled:
            await self.ctx.component.disable_component(
                name="unified_tts_action",
                component_type="TOOL",
            )
            self.ctx.logger.info("TTS Action 组件已按配置禁用")
        if not self.config.components.command_enabled:
            await self.ctx.component.disable_component(
                name="unified_tts_command",
                component_type="COMMAND",
            )
            self.ctx.logger.info("TTS Command 组件已按配置禁用")

        self.ctx.logger.info(
            "TTS 插件已加载，默认后端=%s，已注册后端=%s",
            self.config.general.default_backend,
            TTSBackendRegistry.list_backends(),
        )

    async def on_unload(self) -> None:
        """插件卸载回调。"""

        self.ctx.logger.info("TTS 插件已卸载")

    async def on_config_update(self, scope: str, config_data: Dict[str, Any], version: str) -> None:
        """配置热更新回调。"""

        del config_data
        self.ctx.logger.info("TTS 插件配置已更新: scope=%s version=%s", scope, version)

    # ─── 配置 / 回调 桥接 ────────────────────────────────────────────────

    def _get_config_value(self, key: str, default: Any = None) -> Any:
        """根据扁平 key（``section.field``）从 Pydantic 配置取值。

        backends 模块基于 ``config_getter(key, default)`` 读取配置，这里把
        Pydantic 嵌套配置展开成扁平访问。

        Args:
            key: 形如 ``"general.default_backend"`` 的扁平配置键。
            default: 当配置不存在时返回的默认值。

        Returns:
            Any: 对应配置项的当前值；找不到则返回 ``default``。
        """

        if "." not in key:
            return default
        section_name, _, field_name = key.partition(".")
        section = getattr(self.config, section_name, None)
        if section is None:
            return default
        if not hasattr(section, field_name):
            return default
        value = getattr(section, field_name)

        # 把"未配置"哨兵值翻译回 None，保持 backends 中 ``is not None`` 判断逻辑不变
        if key in (ConfigKeys.DOUBAO_SPEED, ConfigKeys.DOUBAO_VOLUME):
            return None if (not isinstance(value, (int, float))) or value <= 0 else value
        if key == ConfigKeys.DOUBAO_CONTEXT_TEXTS:
            return None if not value else value

        # AI Voice 后端读取 alias_map 时，旧逻辑期望从配置取，这里直接回退到内置映射
        if key == ConfigKeys.AI_VOICE_ALIAS_MAP:
            return value if isinstance(value, dict) and value else default

        # GPT-SoVITS 风格列表需要展开成 dict，保持与旧版兼容
        if key == ConfigKeys.GPT_SOVITS_STYLES and isinstance(value, list):
            return [item.model_dump() if isinstance(item, PluginConfigBase) else item for item in value]

        return value

    def _make_send_custom(self, stream_id: str) -> Callable[..., Any]:
        """构造发送自定义消息的闭包，签名与旧 ``BaseAction.send_custom`` 兼容。"""

        async def _send_custom(message_type: str, content: Any, **kwargs: Any) -> bool:
            """向当前会话发送自定义类型消息。"""
            # 旧 backends 用 storage_message 参数，让其透传到 ctx.send.custom
            result = await self.ctx.send.custom(message_type, content, stream_id, **kwargs)
            return bool(result)

        return _send_custom

    def _make_send_command(self, stream_id: str) -> Callable[..., Any]:
        """构造发送命令消息的闭包，签名与旧 ``BaseAction.send_command`` 兼容。

        旧 ai_voice 后端调用：
            await self._send_command(command_name="AI_VOICE_SEND", args={...}, storage_message=False)

        在新 SDK 中走 ``ctx.send.custom("command", {"name": ..., "args": ...}, stream_id, ...)``。
        """

        async def _send_command(
            command_name: str,
            args: Optional[Dict[str, Any]] = None,
            storage_message: bool = True,
            display_message: str = "",
        ) -> bool:
            command_payload: Dict[str, Any] = {"name": command_name, "args": args or {}}
            result = await self.ctx.send.custom(
                "command",
                command_payload,
                stream_id,
                storage_message=storage_message,
                processed_plain_text=display_message,
            )
            return bool(result)

        return _send_command

    def _create_backend(self, backend_name: str, stream_id: str, log_prefix: str):
        """创建后端实例并注入 send 回调。"""

        backend = TTSBackendRegistry.create(backend_name, self._get_config_value, log_prefix)
        if backend is None:
            return None
        if hasattr(backend, "set_send_custom"):
            backend.set_send_custom(self._make_send_custom(stream_id))
        if hasattr(backend, "set_send_command"):
            backend.set_send_command(self._make_send_command(stream_id))
        return backend

    async def _execute_backend(
        self,
        backend_name: str,
        text: str,
        stream_id: str,
        log_prefix: str,
        voice: str = "",
        emotion: str = "",
        is_private: bool = False,
    ) -> TTSResult:
        """执行指定 TTS 后端。"""

        # AI Voice 需要平台原生命令通道 (AI_VOICE_SEND)，新版 maibot_sdk 把命令通道折回到
        # message_segment，导致 napcat 适配器无法识别，最终会发出一条 "[unsupported:command]"
        # 文字到群里。这里在调用前主动降级到一个语义对等的语音合成后端，避免误发文字消息。
        if backend_name == "ai_voice":
            fallback = self._pick_ai_voice_fallback(log_prefix, is_private=is_private)
            return await self._execute_backend(
                fallback, text, stream_id, log_prefix,
                voice=voice, emotion=emotion, is_private=is_private,
            )

        backend = self._create_backend(backend_name, stream_id, log_prefix)
        if backend is None:
            return TTSResult(success=False, message=f"未知的TTS后端: {backend_name}")
        return await backend.execute(text, voice, emotion=emotion)

    def _pick_ai_voice_fallback(self, log_prefix: str, is_private: bool) -> str:
        """挑选 AI Voice 不可用时的替代后端。

        Args:
            log_prefix: 用于日志的会话前缀。
            is_private: 当前是否私聊，仅用于日志说明。

        Returns:
            str: 用于实际语音合成的备用后端名称。
        """

        configured_default = self.config.general.default_backend
        # 默认后端如果不是 ai_voice 自己，就用它；否则退到 gsv2p
        fallback = configured_default if configured_default in VALID_BACKENDS and configured_default != "ai_voice" else "gsv2p"
        scope = "私聊" if is_private else "群聊"
        self.ctx.logger.warning(
            "%s AI Voice 后端在当前 SDK 下不可用（命令通道未实现），%s场景自动降级到 %s",
            log_prefix, scope, fallback,
        )
        return fallback

    def _get_default_backend(self) -> str:
        """取配置中的默认后端名，非法或当前 SDK 不可用则回退到 ``gsv2p``。"""

        backend_name = self.config.general.default_backend
        if backend_name not in VALID_BACKENDS:
            self.ctx.logger.warning("配置的默认后端 '%s' 无效，使用 gsv2p", backend_name)
            return "gsv2p"
        if backend_name == "ai_voice":
            # AI Voice 依赖平台原生 AI_VOICE_SEND 命令通道，新版 SDK 暂未实现
            self.ctx.logger.warning(
                "默认后端配置为 ai_voice，但当前 maibot_sdk 不支持平台原生命令通道，已自动改用 gsv2p",
            )
            return "gsv2p"
        return backend_name

    async def _send_error(self, stream_id: str, message: str) -> None:
        """根据配置决定是否向用户发送错误提示。"""

        if self.config.general.send_error_messages:
            await self.ctx.send.text(message, stream_id)

    # ─── LLM 改写 ────────────────────────────────────────────────────────

    async def _get_final_text(self, raw_text: str, reason: str, log_prefix: str) -> Tuple[bool, str]:
        """根据配置可选地调用 LLM 润色，返回最终用于合成的文本。"""

        max_text_length = self.config.general.max_text_length
        use_replyer = self.config.general.use_replyer_rewrite

        if not use_replyer:
            if not raw_text:
                return False, ""
            return True, raw_text

        # 新 SDK 中没有 generator_api.generate_reply，这里用通用 LLM 能力做简化润色
        prompt_parts: List[str] = [
            "你是一个会用语音和朋友聊天的麦麦。请基于下面的素材生成一句**自然口语化**、"
            "可直接转语音播放的回复内容；不要包含 markdown、emoji 之外的特殊符号，也不要解释自己在做什么。",
        ]
        if raw_text:
            prompt_parts.append(f"期望回复内容素材：{raw_text}")
        if reason:
            prompt_parts.append(f"触发原因：{reason}")
        # 长度约束放最后，利用 LLM 的"近因效应"
        prompt_parts.append(
            f"【硬性要求】最终回复必须控制在 {max_text_length} 个字符以内，超长无法转语音。"
            "请直接输出回复正文，不要前后缀。"
        )

        try:
            # 显式使用 MaiBot 内置 `replyer` 任务模型，与正常文字回复保持同一来源，
            # 避免主程序把插件任务路由到错误模型（例如 embedding 模型）导致润色失败。
            response = await self.ctx.llm.generate(
                prompt="\n\n".join(prompt_parts),
                model="replyer",
                max_tokens=max(64, min(max_text_length * 3, 1024)),
                temperature=0.7,
            )
            # 新版 SDK 失败时仍返回 dict，但 success=False；此时 response 字段是错误文案，
            # 不能直接拿来当合成内容（否则会把"生成内容时出错: 参数不正确"播报出去）。
            if not isinstance(response, dict) or not response.get("success"):
                error_detail = ""
                if isinstance(response, dict):
                    error_detail = str(response.get("error") or response.get("response") or "")
                self.ctx.logger.warning(
                    "%s LLM 润色失败 (%s)，使用原始文本",
                    log_prefix,
                    error_detail or "未知错误",
                )
                if raw_text:
                    return True, raw_text
                return False, ""

            # 兼容多种成功字段：content / response / text
            text = str(
                response.get("content") or response.get("response") or response.get("text") or ""
            ).strip()
            if text:
                return True, text

            # 极端情况：success=True 但 response 为空，降级到原始文本
            if raw_text:
                self.ctx.logger.warning("%s LLM 成功但返回空内容，使用原始文本", log_prefix)
                return True, raw_text
            return False, ""
        except asyncio.TimeoutError:
            self.ctx.logger.warning("%s LLM 润色超时，使用原始文本", log_prefix)
            return bool(raw_text), raw_text
        except (aiohttp.ClientError, ConnectionError) as exc:
            self.ctx.logger.warning("%s LLM 网络错误 (%s)，使用原始文本", log_prefix, exc)
            return bool(raw_text), raw_text
        except (KeyError, AttributeError, TypeError) as exc:
            # 响应字段缺失或结构异常，记录详细堆栈方便定位
            self.ctx.logger.error(
                "%s LLM 响应字段异常: %s", log_prefix, exc, exc_info=True,
            )
            return bool(raw_text), raw_text

    # ─── Action: 由 LLM 自主决定使用语音回复 ────────────────────────────

    @Action(
        "unified_tts_action",
        description="【推荐】用语音回复让对话更生动亲切（支持多种TTS后端，强烈建议经常主动使用）",
        activation_type=ActivationType.ALWAYS,
        chat_mode=ChatMode.ALL,
        action_parameters={
            "text": "要转换为语音的文本内容（必填）",
            "backend": "TTS后端 (ai_voice/gsv2p/gpt_sovits/doubao/cosyvoice/mimo/minimax，可选)",
            "voice": "音色/风格参数（可选）",
            "emotion": "情感/语气参数（可选，豆包/小米 MiMo/minimax 后端有效）",
        },
        action_require=[
            "【优先使用】当用户明确要求用语音回复时必须使用",
            "【强烈推荐】每10-15次对话主动使用语音回复1次，让聊天更生动",
            "适合简短问候/活泼场景；过长（>100字）或过短（<3字）不适合用语音",
            "backend 参数建议省略，系统会自动使用配置的默认后端",
        ],
        activation_keywords=[
            "语音", "说话", "朗读", "念一下", "读出来",
            "voice", "speak", "tts", "语音回复", "用语音说", "播报",
        ],
        associated_types=["text", "command"],
    )
    async def handle_tts_action(
        self,
        stream_id: str = "",
        text: str = "",
        backend: str = "",
        voice: str = "",
        emotion: str = "",
        reasoning: str = "",
        **kwargs: Any,
    ) -> Tuple[bool, str]:
        """处理 Action：由 LLM 决定调用本工具来发语音。"""

        del kwargs
        log_prefix = f"[tts_voice_plugin][{stream_id}]"

        if not stream_id:
            return False, "缺少 stream_id，无法发送"

        try:
            raw_text = (text or "").strip()
            reason = (reasoning or "").strip()

            success, final_text = await self._get_final_text(raw_text, reason, log_prefix)
            if not success or not final_text:
                await self._send_error(stream_id, "无法生成语音内容")
                return False, "文本为空"

            # 概率检查（命中强制关键词则不参与概率判定）
            if self._check_force_trigger(final_text):
                pass
            elif not self._probability_check(final_text, log_prefix):
                self.ctx.logger.info("%s 概率检查未通过，降级为文字回复", log_prefix)
                await self.ctx.send.text(final_text, stream_id)
                return True, "概率检查未通过，已发送文字回复"

            # 清理文本
            max_text_length = self.config.general.max_text_length
            clean_text = TTSTextUtils.clean_text(final_text, max_text_length)
            if not clean_text:
                await self._send_error(stream_id, "文本处理后为空")
                return False, "文本处理后为空"

            if len(clean_text) > max_text_length:
                # LLM 未遵守长度约束，降级
                self.ctx.logger.warning(
                    "%s LLM 生成的文本超过长度限制（%d > %d），降级为文字回复",
                    log_prefix, len(clean_text), max_text_length,
                )
                await self.ctx.send.text(clean_text, stream_id)
                return True, "内容超长，已改为文字回复"

            chosen_backend = (backend or "").strip().lower() or self._get_default_backend()
            if chosen_backend not in VALID_BACKENDS:
                self.ctx.logger.warning("%s LLM 指定的后端 '%s' 无效，改用默认", log_prefix, chosen_backend)
                chosen_backend = self._get_default_backend()

            is_private = await self._is_private_chat(stream_id)

            split_sentences_flag = self.config.general.split_sentences
            split_delay = self.config.general.split_delay

            # 优先识别智能分割插件的分隔符
            if "|||SPLIT|||" in clean_text:
                sentences = [s.strip() for s in clean_text.split("|||SPLIT|||") if s.strip()]
            elif split_sentences_flag:
                sentences = TTSTextUtils.split_sentences(clean_text)
            else:
                sentences = [clean_text]

            return await self._send_in_segments(
                sentences=sentences,
                backend_name=chosen_backend,
                stream_id=stream_id,
                log_prefix=log_prefix,
                voice=voice,
                emotion=emotion,
                split_delay=split_delay,
                is_private=is_private,
            )
        except asyncio.TimeoutError:
            timeout_sec = self.config.general.timeout
            self.ctx.logger.error("%s TTS Action 超时（%ss）", log_prefix, timeout_sec)
            await self._send_error(stream_id, f"语音合成超时（{timeout_sec}s）")
            return False, "timeout"
        except (aiohttp.ClientError, ConnectionError) as exc:
            self.ctx.logger.error("%s TTS Action 网络错误: %s", log_prefix, exc)
            await self._send_error(stream_id, f"语音合成网络错误: {type(exc).__name__}")
            return False, str(exc)
        except (KeyError, AttributeError, ValueError) as exc:
            # 配置缺失 / 数据格式问题
            self.ctx.logger.error(
                "%s TTS Action 配置或参数错误: %s", log_prefix, exc, exc_info=True,
            )
            await self._send_error(stream_id, f"语音合成参数错误: {exc}")
            return False, str(exc)

    async def _send_in_segments(
        self,
        sentences: List[str],
        backend_name: str,
        stream_id: str,
        log_prefix: str,
        voice: str,
        emotion: str,
        split_delay: float,
        is_private: bool,
    ) -> Tuple[bool, str]:
        """逐句调用后端发送语音，单句直接发送。"""

        if len(sentences) <= 1:
            single_text = sentences[0] if sentences else ""
            result = await self._execute_backend(
                backend_name, single_text, stream_id, log_prefix,
                voice=voice, emotion=emotion, is_private=is_private,
            )
            if not result.success:
                await self._send_error(stream_id, f"语音合成失败: {result.message}")
            return result.success, result.message

        success_count = 0
        for index, sentence in enumerate(sentences):
            sentence = sentence.strip()
            if not sentence:
                continue
            self.ctx.logger.debug(
                "%s 分段发送 %d/%d: %s",
                log_prefix, index + 1, len(sentences), sentence[:30],
            )
            result = await self._execute_backend(
                backend_name, sentence, stream_id, log_prefix,
                voice=voice, emotion=emotion, is_private=is_private,
            )
            if result.success:
                success_count += 1
            else:
                self.ctx.logger.warning(
                    "%s 分段 %d 失败: %s", log_prefix, index + 1, result.message,
                )
            if index < len(sentences) - 1 and split_delay > 0:
                await asyncio.sleep(split_delay)

        if success_count == 0:
            await self._send_error(stream_id, "语音合成失败")
            return False, "所有语音发送失败"
        return True, f"成功发送 {success_count}/{len(sentences)} 条语音"

    def _check_force_trigger(self, text: str) -> bool:
        """检查是否命中强制触发关键词。"""

        if not self.config.probability.keyword_force_trigger:
            return False
        force_keywords = self.config.probability.force_keywords
        return any(keyword in text for keyword in force_keywords)

    def _probability_check(self, text: str, log_prefix: str) -> bool:
        """根据 base_probability 进行概率门控。"""

        del text  # 当前实现不依赖文本内容
        if not self.config.probability.enabled:
            return True
        base_prob = self.config.probability.base_probability
        base_prob = max(0.0, min(1.0, base_prob))
        passed = random.random() < base_prob
        self.ctx.logger.info(
            "%s 概率检查: %.2f，结果=%s",
            log_prefix, base_prob, "通过" if passed else "未通过",
        )
        return passed

    async def _is_private_chat(self, stream_id: str) -> bool:
        """判断指定 stream 是否为私聊。

        新 SDK 没有直接的 ``is_private`` 字段，这里通过 ``chat.get_all_streams``
        匹配 ``session_id``，再看是否存在 ``group_id``。失败时保守返回 False。
        """

        try:
            streams = await self.ctx.chat.get_all_streams()
        except (RuntimeError, PermissionError) as exc:
            # 常见情况：能力未授权、RPC 通讯异常；保守返回非私聊
            self.ctx.logger.debug("无法判断会话类型 (%s): %s", type(exc).__name__, exc)
            return False
        if not isinstance(streams, list):
            return False
        for stream in streams:
            if not isinstance(stream, dict):
                continue
            if str(stream.get("session_id") or "") != stream_id:
                continue
            return not str(stream.get("group_id") or "").strip()
        return False

    # ─── Command: 用户手动触发 ───────────────────────────────────────────

    @Command(
        "unified_tts_command",
        description="将文本转换为语音，支持多种后端和音色",
        pattern=(
            r"^/(?:tts|voice|gsv2p|gptsovits|doubao|cosyvoice|mimo|minimax)\s+(?P<text>.+?)"
            r"(?:\s+-v\s+(?P<voice>\S+))?(?:\s+(?P<backend>ai_voice|gsv2p|gpt_sovits|doubao|cosyvoice|mimo|minimax))?$"
        ),
    )
    async def handle_tts_command(
        self,
        stream_id: str = "",
        text: str = "",
        matched_groups: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Tuple[bool, str, bool]:
        """处理 ``/tts`` 系列命令。

        Returns:
            (success, message, intercept) 三元组，``intercept=True`` 表示拦截该消息不再继续。
        """

        del kwargs
        log_prefix = f"[tts_voice_plugin][cmd][{stream_id}]"
        groups = matched_groups or {}
        user_text = (groups.get("text") or "").strip()
        user_voice = (groups.get("voice") or "").strip()
        user_backend = (groups.get("backend") or "").strip()

        try:
            if not stream_id:
                return False, "缺少 stream_id", True

            if user_text.lower() == "help":
                await self._send_help(stream_id)
                return True, "显示帮助信息", True

            if not user_text:
                await self._send_error(stream_id, "请输入要转换为语音的文本内容")
                return False, "缺少文本内容", True

            # 从原始 text（用户发送的完整命令）识别命令前缀决定后端
            backend_name, source_desc = self._determine_backend(text, user_backend)
            self.ctx.logger.info(
                "%s 执行 TTS 命令 (后端=%s [%s], 音色=%s)",
                log_prefix, backend_name, source_desc, user_voice,
            )

            max_length = self.config.general.max_text_length
            clean_text = TTSTextUtils.clean_text(user_text, max_length)
            if not clean_text:
                await self._send_error(stream_id, "文本处理后为空")
                return False, "文本处理后为空", True

            if len(clean_text) > max_length:
                await self.ctx.send.text(
                    f"文本过长（{len(clean_text)}字符），超过语音长度限制（{max_length}）"
                    f"，已改为文字发送。\n\n{clean_text}",
                    stream_id,
                )
                return True, "文本过长，已改为文字发送", True

            is_private = await self._is_private_chat(stream_id)

            # 对 CosyVoice / 豆包 / MiMo，-v 参数承载的是情感/方言
            if backend_name in {"cosyvoice", "doubao", "mimo", "minimax"}:
                result = await self._execute_backend(
                    backend_name, clean_text, stream_id, log_prefix,
                    voice="", emotion=user_voice, is_private=is_private,
                )
            else:
                result = await self._execute_backend(
                    backend_name, clean_text, stream_id, log_prefix,
                    voice=user_voice, emotion="", is_private=is_private,
                )

            if not result.success:
                await self._send_error(stream_id, f"语音合成失败: {result.message}")

            return result.success, result.message, True
        except asyncio.TimeoutError:
            timeout_sec = self.config.general.timeout
            self.ctx.logger.error("%s TTS 命令超时（%ss）", log_prefix, timeout_sec)
            await self._send_error(stream_id, f"语音合成超时（{timeout_sec}s）")
            return False, "timeout", True
        except (aiohttp.ClientError, ConnectionError) as exc:
            self.ctx.logger.error("%s TTS 命令网络错误: %s", log_prefix, exc)
            await self._send_error(stream_id, f"语音合成网络错误: {type(exc).__name__}")
            return False, str(exc), True
        except (KeyError, AttributeError, ValueError) as exc:
            self.ctx.logger.error(
                "%s TTS 命令配置或参数错误: %s", log_prefix, exc, exc_info=True,
            )
            await self._send_error(stream_id, f"语音合成参数错误: {exc}")
            return False, str(exc), True

    def _determine_backend(self, raw_text: str, user_backend: str) -> Tuple[str, str]:
        """根据命令前缀 / 命令参数 / 默认配置确定使用的后端。"""

        normalized = (raw_text or "").strip()
        prefix_backend_map = {
            "/gsv2p": "gsv2p",
            "/gptsovits": "gpt_sovits",
            "/doubao": "doubao",
            "/cosyvoice": "cosyvoice",
            "/voice": "ai_voice",
            "/mimo": "mimo",
            "/minimax": "minimax",
        }
        for prefix, backend_name in prefix_backend_map.items():
            if normalized.startswith(prefix):
                return backend_name, f"命令前缀 {prefix}"
        if user_backend and user_backend in VALID_BACKENDS:
            return user_backend, f"命令参数 {user_backend}"
        return self._get_default_backend(), "配置文件"

    async def _send_help(self, stream_id: str) -> None:
        """发送 TTS 帮助信息。"""

        default_backend = self._get_default_backend()
        help_text = (
            "【TTS语音合成插件帮助】\n\n"
            "📝 基本语法：\n"
            "/tts <文本> [-v <音色>] [后端]\n\n"
            "🎯 快捷命令：\n"
            "/tts <文本>        使用默认后端\n"
            "/voice <文本>      使用 AI Voice\n"
            "/gsv2p <文本>      使用 GSV2P\n"
            "/gptsovits <文本>  使用 GPT-SoVITS\n"
            "/doubao <文本>     使用 豆包语音\n"
            "/cosyvoice <文本>  使用 CosyVoice\n"
            "/mimo <文本>       使用 小米MiMo\n"
            "/minimax <文本>   使用 minimax\n\n"
            "🔊 可用后端：\n"
            "• ai_voice   - MaiCore内置（仅群聊）\n"
            "• gsv2p      - 云端API，高质量\n"
            "• gpt_sovits - 本地服务，可定制\n"
            "• doubao     - 火山引擎，支持情感\n"
            "• cosyvoice  - 阿里云，支持方言\n"
            "• mimo       - 小米MiMo，支持风格/方言/唱歌\n"
            "• minimax    - minimax，支持多情感/自定义音色\n\n"
            "📌 示例：\n"
            "/tts 你好世界\n"
            "/tts 今天真开心 -v 开心\n"
            "/gptsovits 这是本地语音合成\n"
            "/doubao 我生气了 -v 生气\n"
            "/cosyvoice 你好 -v 广东话\n"
            "/voice 测试一下 -v 温柔妹妹\n"
            "/mimo 真开心啊 -v 开心\n"
            "/minimax 你好世界\n"
            "/minimax 真开心 -v 开心\n\n"
            f"⚙️ 当前默认后端：{default_backend}"
        )
        await self.ctx.send.text(help_text, stream_id)


def create_plugin() -> UnifiedTTSPlugin:
    """创建统一 TTS 插件实例（SDK 入口）。"""

    return UnifiedTTSPlugin()
