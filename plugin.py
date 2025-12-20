"""
统一TTS语音合成插件
支持五种后端：AI Voice (MaiCore内置) / GSV2P (云API) / GPT-SoVITS (本地服务) / 豆包语音 (云API) / CosyVoice (ModelScope Gradio)

Version: 3.2.0
Author: 靓仔
"""

import asyncio
import random
from typing import List, Tuple, Type, Optional

from src.common.logger import get_logger
from src.plugin_system.base.base_plugin import BasePlugin
from src.plugin_system.apis.plugin_register_api import register_plugin
from src.plugin_system.base.base_action import BaseAction, ActionActivationType
from src.plugin_system.base.base_command import BaseCommand
from src.plugin_system.base.component_types import ComponentInfo, ChatMode
from src.plugin_system.base.config_types import ConfigField
from src.plugin_system.apis import generator_api

# 导入模块化的后端和工具
from .backends import TTSBackendRegistry, TTSResult
from .backends.ai_voice import AI_VOICE_ALIAS_MAP
from .backends.doubao import DOUBAO_EMOTION_MAP
from .utils.text import TTSTextUtils
from .config_keys import ConfigKeys

logger = get_logger("tts_voice_plugin")

# 有效后端列表
VALID_BACKENDS = ["ai_voice", "gsv2p", "gpt_sovits", "doubao", "cosyvoice"]


class TTSExecutorMixin:
    """
    TTS执行器混入类

    提供 Action 和 Command 共享的后端执行逻辑
    """

    def _create_backend(self, backend_name: str):
        """
        创建后端实例

        Args:
            backend_name: 后端名称

        Returns:
            后端实例
        """
        backend = TTSBackendRegistry.create(
            backend_name,
            self.get_config,
            self.log_prefix
        )

        if backend:
            # 注入必要的回调函数
            if hasattr(backend, 'set_send_custom'):
                backend.set_send_custom(self.send_custom)
            if hasattr(backend, 'set_send_command'):
                backend.set_send_command(self.send_command)

        return backend

    async def _execute_backend(
        self,
        backend_name: str,
        text: str,
        voice: str = "",
        emotion: str = ""
    ) -> TTSResult:
        """
        执行指定后端

        Args:
            backend_name: 后端名称
            text: 待转换文本
            voice: 音色
            emotion: 情感（豆包后端）

        Returns:
            TTSResult
        """
        backend = self._create_backend(backend_name)

        if not backend:
            return TTSResult(
                success=False,
                message=f"未知的TTS后端: {backend_name}"
            )

        # AI Voice 私聊限制检查
        if backend_name == "ai_voice":
            is_private = self._check_is_private_chat()
            if is_private:
                logger.info(f"{self.log_prefix} AI语音仅支持群聊，自动切换到GSV2P后端")
                return await self._execute_backend("gsv2p", text, voice, emotion)

        return await backend.execute(text, voice, emotion=emotion)

    def _check_is_private_chat(self) -> bool:
        """检查是否是私聊"""
        # Action 中使用 chat_stream
        if hasattr(self, 'chat_stream'):
            return not getattr(self.chat_stream, 'group_info', None)
        # Command 中使用 message
        if hasattr(self, 'message'):
            msg_info = getattr(self.message, 'message_info', None)
            if msg_info:
                return not getattr(msg_info, 'group_info', None)
        return False

    def _get_default_backend(self) -> str:
        """获取配置的默认后端"""
        backend = self.get_config(ConfigKeys.GENERAL_DEFAULT_BACKEND, "gsv2p")
        if backend not in VALID_BACKENDS:
            logger.warning(f"{self.log_prefix} 配置的默认后端 '{backend}' 无效，使用 gsv2p")
            return "gsv2p"
        return backend


class UnifiedTTSAction(BaseAction, TTSExecutorMixin):
    """统一TTS Action - LLM自动触发"""

    action_name = "unified_tts_action"
    action_description = "用语音回复（支持AI Voice/GSV2P/GPT-SoVITS/豆包语音多后端）"
    activation_type = ActionActivationType.LLM_JUDGE
    mode_enable = ChatMode.ALL
    parallel_action = False

    activation_keywords = [
        "语音", "说话", "朗读", "念一下", "读出来",
        "voice", "speak", "tts", "语音回复", "用语音说", "播报"
    ]
    keyword_case_sensitive = False

    action_parameters = {
        "text": "要转换为语音的文本内容（必填）",
        "backend": "TTS后端引擎 (ai_voice/gsv2p/gpt_sovits/doubao/cosyvoice，可选，建议省略让系统自动使用配置的默认后端)",
        "voice": "音色/风格参数（可选）",
        "emotion": "情感/语气参数（可选，仅豆包后端有效）。支持：开心/兴奋/温柔/骄傲/生气/愤怒/伤心/失望/委屈/平静/严肃/疑惑/慢速/快速/小声/大声等"
    }

    action_require = [
        "当用户要求用语音回复时使用",
        "当回复简短问候语时使用（如早上好、晚安、你好等）",
        "当想让回复更活泼生动时可以使用",
        "注意：回复内容过长或者过短不适合用语音",
        "注意：backend参数建议省略，系统会自动使用配置的默认后端"
    ]

    associated_types = ["text", "command"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timeout = self.get_config(ConfigKeys.GENERAL_TIMEOUT, 60)
        self.max_text_length = self.get_config(ConfigKeys.GENERAL_MAX_TEXT_LENGTH, 500)

    def _check_force_trigger(self, text: str) -> bool:
        """检查是否强制触发"""
        if not self.get_config(ConfigKeys.PROBABILITY_KEYWORD_FORCE_TRIGGER, True):
            return False
        force_keywords = self.get_config(
            ConfigKeys.PROBABILITY_FORCE_KEYWORDS,
            ["一定要用语音", "必须语音", "语音回复我", "务必用语音"]
        )
        return any(kw in text for kw in force_keywords)

    def _probability_check(self, text: str) -> bool:
        """概率控制检查"""
        if not self.get_config(ConfigKeys.PROBABILITY_ENABLED, True):
            return True

        base_prob = self.get_config(ConfigKeys.PROBABILITY_BASE_PROBABILITY, 1.0)
        base_prob = max(0.0, min(1.0, base_prob))
        result = random.random() < base_prob
        logger.info(f"{self.log_prefix} 概率检查: {base_prob:.2f}, 结果={'通过' if result else '未通过'}")
        return result

    async def _get_final_text(self, raw_text: str, reason: str, use_replyer: bool) -> Tuple[bool, str]:
        """获取最终要转语音的文本（使用与正常回复一致的prompt参数）"""
        max_text_length = self.get_config(ConfigKeys.GENERAL_MAX_TEXT_LENGTH, 200)

        if not use_replyer:
            if not raw_text:
                return False, ""
            return True, raw_text

        try:
            # 在生成时就注入长度限制，让LLM直接生成符合约束的文本
            constraint_info = (
                f"注意：生成的内容必须简洁，不超过{max_text_length}个字符"
                f"（因为需要转换成语音播报），如果内容较长需要分段发送。"
            )

            # 统一使用 generate_reply 以确保触发 POST_LLM 事件（日程注入）
            # rewrite_reply 不会触发 POST_LLM 事件，因此不适用
            extra_info_parts = [constraint_info]
            if raw_text:
                extra_info_parts.append(f"期望的回复内容：{raw_text}")

            success, llm_response = await generator_api.generate_reply(
                chat_stream=self.chat_stream,
                reply_message=self.action_message,
                reply_reason=reason,
                extra_info="\n".join(extra_info_parts),
                request_type="tts_voice_plugin",
                from_plugin=False  # 允许触发POST_LLM事件，使日程注入生效
            )
            if success and llm_response and llm_response.content:
                logger.info(f"{self.log_prefix} 语音内容生成成功")
                return True, llm_response.content.strip()

            # 如果生成失败但有原始文本，则使用原始文本
            if raw_text:
                logger.warning(f"{self.log_prefix} 内容生成失败，使用原始文本")
                return True, raw_text

            return False, ""
        except Exception as e:
            logger.error(f"{self.log_prefix} 调用 replyer 出错: {e}")
            return bool(raw_text), raw_text

    async def execute(self) -> Tuple[bool, str]:
        """执行TTS语音合成"""
        try:
            raw_text = self.action_data.get("text", "").strip()
            voice = self.action_data.get("voice", "")
            reason = self.action_data.get("reason", "")
            emotion = self.action_data.get("emotion", "")

            use_replyer = self.get_config(ConfigKeys.GENERAL_USE_REPLYER_REWRITE, True)

            # 获取最终文本
            success, final_text = await self._get_final_text(raw_text, reason, use_replyer)
            if not success or not final_text:
                await self.send_text("无法生成语音内容")
                return False, "文本为空"

            # 概率检查
            force_trigger = self._check_force_trigger(final_text)
            if not force_trigger and not self._probability_check(final_text):
                logger.info(f"{self.log_prefix} 概率检查未通过，使用文字回复")
                await self.send_text(final_text)
                await self.store_action_info(
                    action_build_into_prompt=True,
                    action_prompt_display=f"回复了文字消息：{final_text[:50]}...",
                    action_done=True
                )
                return True, "概率检查未通过，已发送文字回复"

            # 清理文本（移除特殊字符，替换网络用语）
            # 注意：长度应该由LLM在生成时就遵守，这里只做字符清理
            clean_text = TTSTextUtils.clean_text(final_text, self.max_text_length)
            if not clean_text:
                await self.send_text("文本处理后为空")
                return False, "文本处理后为空"

            # 如果清理后的文本仍然超过限制，说明LLM未遵守约束
            if len(clean_text) > self.max_text_length:
                logger.warning(
                    f"{self.log_prefix} LLM生成的文本超过长度限制 "
                    f"({len(clean_text)} > {self.max_text_length}字符)，降级为文字回复"
                )
                await self.send_text(clean_text)
                await self.store_action_info(
                    action_build_into_prompt=True,
                    action_prompt_display="回复了文字消息（内容超过语音限制）",
                    action_done=True
                )
                return True, "内容超过语音长度限制，已改为文字回复"

            # 获取后端并执行
            backend = self._get_default_backend()
            logger.info(f"{self.log_prefix} 使用配置的默认后端: {backend}")

            # 检查是否启用分段发送
            split_sentences = self.get_config(ConfigKeys.GENERAL_SPLIT_SENTENCES, True)
            split_delay = self.get_config(ConfigKeys.GENERAL_SPLIT_DELAY, 0.3)

            if split_sentences:
                # 分段发送模式：将文本分割成句子，逐句发送语音
                sentences = TTSTextUtils.split_sentences(clean_text)

                if len(sentences) > 1:
                    logger.info(f"{self.log_prefix} 分段发送模式：共 {len(sentences)} 句")

                    success_count = 0
                    all_sentences_text = []

                    for i, sentence in enumerate(sentences):
                        if not sentence.strip():
                            continue

                        logger.debug(f"{self.log_prefix} 发送第 {i+1}/{len(sentences)} 句: {sentence[:30]}...")
                        result = await self._execute_backend(backend, sentence, voice, emotion)

                        if result.success:
                            success_count += 1
                            all_sentences_text.append(sentence)
                        else:
                            logger.warning(f"{self.log_prefix} 第 {i+1} 句发送失败: {result.message}")

                        # 句子之间添加延迟
                        if i < len(sentences) - 1 and split_delay > 0:
                            await asyncio.sleep(split_delay)

                    # 记录动作信息
                    if success_count > 0:
                        display_text = "".join(all_sentences_text)
                        await self.store_action_info(
                            action_build_into_prompt=True,
                            action_prompt_display=f"[语音：{display_text}]",
                            action_done=True
                        )
                        return True, f"成功发送 {success_count}/{len(sentences)} 条语音"
                    else:
                        await self.send_text("语音合成失败")
                        return False, "所有语音发送失败"
                else:
                    # 只有一句，正常发送
                    result = await self._execute_backend(backend, clean_text, voice, emotion)
            else:
                # 原有逻辑：整段发送
                result = await self._execute_backend(backend, clean_text, voice, emotion)

            if result.success:
                await self.store_action_info(
                    action_build_into_prompt=True,
                    action_prompt_display=f"[语音：{clean_text}]",
                    action_done=True
                )
            else:
                await self.send_text(f"语音合成失败: {result.message}")

            return result.success, result.message

        except Exception as e:
            error_msg = str(e)
            logger.error(f"{self.log_prefix} TTS语音合成出错: {error_msg}")
            await self.send_text(f"语音合成出错: {error_msg}")
            return False, error_msg


class UnifiedTTSCommand(BaseCommand, TTSExecutorMixin):
    """统一TTS Command - 用户手动触发"""

    command_name = "unified_tts_command"
    command_description = "将文本转换为语音，支持多种后端和音色"
    command_pattern = r"^/(?:tts|voice|gsv2p|gptsovits|doubao|cosyvoice)\s+(?P<text>.+?)(?:\s+-v\s+(?P<voice>\S+))?(?:\s+(?P<backend>ai_voice|gsv2p|gpt_sovits|doubao|cosyvoice))?$"
    command_help = "将文本转换为语音。用法：/tts 你好世界 [-v 音色] [后端]"
    command_examples = [
        "/tts 你好，世界！",
        "/tts 今天天气不错 -v 小新",
        "/gptsovits 你好世界 -v default",
        "/cosyvoice 你好世界 -v 四川话",
        "/tts 试试 -v 温柔妹妹 ai_voice",
        "/gsv2p 你好世界",
        "/doubao 你好世界 -v 开心"
    ]
    intercept_message = True

    async def _send_help(self):
        """发送帮助信息"""
        default_backend = self._get_default_backend()

        help_text = """【TTS语音合成插件帮助】

📝 基本语法：
/tts <文本> [-v <音色>] [后端]

🎯 快捷命令：
/tts <文本>        使用默认后端
/voice <文本>      使用 AI Voice
/gsv2p <文本>      使用 GSV2P
/gptsovits <文本>  使用 GPT-SoVITS
/doubao <文本>     使用 豆包语音
/cosyvoice <文本>  使用 CosyVoice

🔊 可用后端：
• ai_voice   - MaiCore内置（仅群聊）
• gsv2p      - 云端API，高质量
• gpt_sovits - 本地服务，可定制
• doubao     - 火山引擎，支持情感
• cosyvoice  - 阿里云，支持方言

🎭 音色/情感参数（-v）：
• AI Voice: 小新、温柔妹妹、霸道总裁、妲己 等22种
• GSV2P: 原神-中文-派蒙_ZH 等（见API文档）
• 豆包: 开心、生气、伤心、撒娇、严肃 等
• CosyVoice: 广东话、四川话、东北话、开心、慢速 等

📌 示例：
/tts 你好世界
/tts 今天真开心 -v 开心
/gptsovits 这是本地语音合成
/doubao 我生气了 -v 生气
/cosyvoice 你好 -v 广东话
/voice 测试一下 -v 温柔妹妹

⚙️ 当前默认后端：""" + default_backend

        await self.send_text(help_text)

    def _determine_backend(self, user_backend: str) -> Tuple[str, str]:
        """
        确定使用的后端

        Returns:
            (backend_name, source_description)
        """
        # 1. 检查命令前缀
        raw_text = self.message.raw_message if self.message.raw_message else self.message.processed_plain_text
        if raw_text:
            # 命令前缀到后端的映射
            prefix_backend_map = {
                "/gsv2p": "gsv2p",
                "/gptsovits": "gpt_sovits",
                "/doubao": "doubao",
                "/cosyvoice": "cosyvoice",
                "/voice": "ai_voice",
            }
            for prefix, backend in prefix_backend_map.items():
                if raw_text.startswith(prefix):
                    return backend, f"命令前缀 {prefix}"

        # 2. 检查命令参数
        if user_backend and user_backend in VALID_BACKENDS:
            return user_backend, f"命令参数 {user_backend}"

        # 3. 使用配置文件默认值
        return self._get_default_backend(), "配置文件"

    async def execute(self) -> Tuple[bool, str, bool]:
        """执行TTS命令"""
        try:
            text = self.matched_groups.get("text", "").strip()
            voice = self.matched_groups.get("voice", "")
            user_backend = self.matched_groups.get("backend", "")

            # 处理帮助命令
            if text.lower() == "help":
                await self._send_help()
                return True, "显示帮助信息", True

            if not text:
                await self.send_text("请输入要转换为语音的文本内容")
                return False, "缺少文本内容", True

            # 确定后端
            backend, backend_source = self._determine_backend(user_backend)

            # 清理文本
            max_length = self.get_config(ConfigKeys.GENERAL_MAX_TEXT_LENGTH, 500)
            clean_text = TTSTextUtils.clean_text(text, max_length)

            if not clean_text:
                await self.send_text("文本处理后为空")
                return False, "文本处理后为空", True

            # 检查长度限制
            if len(clean_text) > max_length:
                await self.send_text(
                    f"文本过长（{len(clean_text)}字符），"
                    f"超过语音合成限制（{max_length}字符），"
                    f"已改为文字发送。\n\n{clean_text}"
                )
                return True, "文本过长，已改为文字发送", True

            logger.info(f"{self.log_prefix} 执行TTS命令 (后端: {backend} [来源: {backend_source}], 音色: {voice})")

            # 执行后端
            # 对于 CosyVoice 和豆包，voice 参数实际上是情感/方言
            if backend in ["cosyvoice", "doubao"]:
                result = await self._execute_backend(backend, clean_text, voice="", emotion=voice)
            else:
                result = await self._execute_backend(backend, clean_text, voice)

            if not result.success:
                await self.send_text(f"语音合成失败: {result.message}")

            return result.success, result.message, True

        except Exception as e:
            logger.error(f"{self.log_prefix} TTS命令执行出错: {e}")
            await self.send_text(f"语音合成出错: {e}")
            return False, f"执行出错: {e}", True


@register_plugin
class UnifiedTTSPlugin(BasePlugin):
    """统一TTS语音合成插件 - 支持多后端的文本转语音插件"""

    plugin_name = "tts_voice_plugin"
    plugin_description = "统一TTS语音合成插件，支持AI Voice、GSV2P、GPT-SoVITS、豆包语音多种后端"
    plugin_version = "3.1.0"
    plugin_author = "靓仔"
    enable_plugin = True
    config_file_name = "config.toml"
    dependencies = []
    python_dependencies = ["aiohttp"]

    config_section_descriptions = {
        "plugin": "插件基本配置",
        "general": "通用设置",
        "components": "组件启用控制",
        "probability": "概率控制配置",
        "ai_voice": "AI Voice后端配置",
        "gsv2p": "GSV2P后端配置",
        "gpt_sovits": "GPT-SoVITS后端配置",
        "doubao": "豆包语音后端配置",
        "cosyvoice": "CosyVoice后端配置"
    }

    config_schema = {
        "plugin": {
            "enabled": ConfigField(type=bool, default=True, description="是否启用插件"),
            "config_version": ConfigField(type=str, default="3.2.0", description="配置文件版本")
        },
        "general": {
            "default_backend": ConfigField(
                type=str, default="doubao",
                description="默认TTS后端 (ai_voice/gsv2p/gpt_sovits/doubao/cosyvoice)"
            ),
            "timeout": ConfigField(type=int, default=60, description="请求超时时间（秒）"),
            "max_text_length": ConfigField(
                type=int, default=200,
                description="最大文本长度（该限制会在调用LLM时注入到prompt中，让LLM直接生成符合长度的回复，而不是被动截断）"
            ),
            "use_replyer_rewrite": ConfigField(
                type=bool, default=True,
                description="是否使用replyer润色语音内容"
            ),
            "audio_output_dir": ConfigField(
                type=str, default="",
                description="音频文件输出目录（支持相对路径和绝对路径，留空使用项目根目录）"
            ),
            "use_base64_audio": ConfigField(
                type=bool, default=True,
                description="是否使用base64编码发送音频（备选方案）"
            ),
            "split_sentences": ConfigField(
                type=bool, default=True,
                description="是否分段发送语音（每句话单独发送一条语音，避免长语音播放问题）"
            ),
            "split_delay": ConfigField(
                type=float, default=0.3,
                description="分段发送时每条语音之间的延迟（秒）"
            )
        },
        "components": {
            "action_enabled": ConfigField(type=bool, default=True, description="是否启用Action组件"),
            "command_enabled": ConfigField(type=bool, default=True, description="是否启用Command组件")
        },
        "probability": {
            "enabled": ConfigField(type=bool, default=True, description="是否启用概率控制"),
            "base_probability": ConfigField(type=float, default=1.0, description="基础触发概率"),
            "keyword_force_trigger": ConfigField(type=bool, default=True, description="关键词强制触发"),
            "force_keywords": ConfigField(
                type=list,
                default=["一定要用语音", "必须语音", "语音回复我", "务必用语音"],
                description="强制触发关键词"
            )
        },
        "ai_voice": {
            "default_character": ConfigField(type=str, default="邻家小妹", description="默认AI语音音色"),
            "alias_map": ConfigField(type=dict, default=AI_VOICE_ALIAS_MAP, description="音色别名映射")
        },
        "gsv2p": {
            "api_url": ConfigField(
                type=str, default="https://gsv2p.acgnai.top/v1/audio/speech",
                description="GSV2P API地址"
            ),
            "api_token": ConfigField(type=str, default="", description="API认证Token"),
            "default_voice": ConfigField(type=str, default="原神-中文-派蒙_ZH", description="默认音色"),
            "timeout": ConfigField(type=int, default=60, description="API请求超时（秒）"),
            "model": ConfigField(type=str, default="tts-v4", description="TTS模型"),
            "response_format": ConfigField(type=str, default="mp3", description="音频格式"),
            "speed": ConfigField(type=float, default=1.0, description="语音速度")
        },
        "gpt_sovits": {
            "server": ConfigField(
                type=str, default="http://127.0.0.1:9880",
                description="GPT-SoVITS服务地址"
            ),
            "styles": ConfigField(
                type=dict,
                default={
                    "default": {
                        "refer_wav": "",
                        "prompt_text": "",
                        "prompt_language": "zh",
                        "gpt_weights": "",
                        "sovits_weights": ""
                    }
                },
                description="语音风格配置"
            )
        },
        "doubao": {
            "api_url": ConfigField(
                type=str,
                default="https://openspeech.bytedance.com/api/v3/tts/unidirectional",
                description="豆包语音API地址"
            ),
            "app_id": ConfigField(type=str, default="", description="豆包APP ID"),
            "access_key": ConfigField(type=str, default="", description="豆包Access Key"),
            "resource_id": ConfigField(type=str, default="seed-tts-2.0", description="豆包Resource ID"),
            "default_voice": ConfigField(
                type=str, default="zh_female_vv_uranus_bigtts",
                description="默认音色"
            ),
            "timeout": ConfigField(type=int, default=60, description="API请求超时（秒）"),
            "audio_format": ConfigField(type=str, default="mp3", description="音频格式"),
            "sample_rate": ConfigField(type=int, default=24000, description="采样率"),
            "bitrate": ConfigField(type=int, default=128000, description="比特率"),
            "speed": ConfigField(type=float, default=None, description="语音速度（可选）"),
            "volume": ConfigField(type=float, default=None, description="音量（可选）"),
            "context_texts": ConfigField(
                type=list, default=None,
                description="上下文辅助文本（可选，仅豆包2.0模型）"
            )
        },
        "cosyvoice": {
            "gradio_url": ConfigField(
                type=str,
                default="https://funaudiollm-fun-cosyvoice3-0-5b.ms.show/",
                description="Gradio API地址"
            ),
            "default_mode": ConfigField(
                type=str,
                default="自然语言控制",
                description="推理模式（3s极速复刻/自然语言控制）"
            ),
            "default_instruct": ConfigField(
                type=str,
                default="You are a helpful assistant. 请用广东话表达。<|endofprompt|>",
                description="默认指令（用于自然语言控制模式）"
            ),
            "reference_audio": ConfigField(
                type=str,
                default="",
                description="参考音频路径（用于3s极速复刻模式）"
            ),
            "prompt_text": ConfigField(
                type=str,
                default="",
                description="提示文本（用于3s极速复刻模式）"
            ),
            "timeout": ConfigField(type=int, default=120, description="API请求超时（秒）"),
            "audio_format": ConfigField(type=str, default="wav", description="音频格式")
        }
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        """返回插件组件列表"""
        components = []

        try:
            action_enabled = self.get_config(ConfigKeys.COMPONENTS_ACTION_ENABLED, True)
            command_enabled = self.get_config(ConfigKeys.COMPONENTS_COMMAND_ENABLED, True)
        except AttributeError:
            action_enabled = True
            command_enabled = True

        if action_enabled:
            components.append((UnifiedTTSAction.get_action_info(), UnifiedTTSAction))

        if command_enabled:
            components.append((UnifiedTTSCommand.get_command_info(), UnifiedTTSCommand))

        return components
