"""
统一TTS语音合成插件
支持三种后端：AI Voice (MaiCore内置) / GSV2P (云API) / GPT-SoVITS (本地服务)

Version: 3.0.0
Author: 靓仔
"""

from typing import List, Tuple, Type, Optional, Dict, Any
import aiohttp
import asyncio
import os
import re
import json
from src.common.logger import get_logger
from src.plugin_system.base.base_plugin import BasePlugin
from src.plugin_system.apis.plugin_register_api import register_plugin
from src.plugin_system.base.base_action import BaseAction, ActionActivationType
from src.plugin_system.base.base_command import BaseCommand
from src.plugin_system.base.component_types import ComponentInfo, ChatMode
from src.plugin_system.base.config_types import ConfigField
from src.plugin_system.apis import send_api

logger = get_logger("tts_voice_plugin")

# AI Voice 音色映射表
AI_VOICE_ALIAS_MAP = {
    "小新": "lucy-voice-laibixiaoxin", "猴哥": "lucy-voice-houge", "四郎": "lucy-voice-silang",
    "东北老妹儿": "lucy-voice-guangdong-f1", "广西大表哥": "lucy-voice-guangxi-m1",
    "妲己": "lucy-voice-daji", "霸道总裁": "lucy-voice-lizeyan", "酥心御姐": "lucy-voice-suxinjiejie",
    "说书先生": "lucy-voice-m8", "憨憨小弟": "lucy-voice-male1", "憨厚老哥": "lucy-voice-male3",
    "吕布": "lucy-voice-lvbu", "元气少女": "lucy-voice-xueling", "文艺少女": "lucy-voice-f37",
    "磁性大叔": "lucy-voice-male2", "邻家小妹": "lucy-voice-female1", "低沉男声": "lucy-voice-m14",
    "傲娇少女": "lucy-voice-f38", "爹系男友": "lucy-voice-m101", "暖心姐姐": "lucy-voice-female2",
    "温柔妹妹": "lucy-voice-f36", "书香少女": "lucy-voice-f34"
}


class TTSUtils:
    """TTS工具类"""

    @staticmethod
    def clean_text(text: str, max_length: int = 500) -> str:
        """清理文本，移除特殊字符，替换网络用语"""
        # 移除不支持的特殊字符
        text = re.sub(r'[^\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ffa-zA-Z0-9\s，。！？、；：（）【】"\'.,!?;:()\[\]`-]', '', text)

        # 替换常见网络用语
        replacements = {'www': '哈哈哈', 'hhh': '哈哈', '233': '哈哈', '666': '厉害', '88': '拜拜', '...': '。', '……': '。'}
        for old, new in replacements.items():
            text = text.replace(old, new)

        # 限制长度
        if len(text) > max_length:
            text = text[:max_length] + "。"

        return text.strip()

    @staticmethod
    def detect_language(text: str) -> str:
        """检测文本语言（zh/ja/en）"""
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        english_chars = len(re.findall(r'[a-zA-Z]', text))
        japanese_chars = len(re.findall(r'[\u3040-\u309f\u30a0-\u30ff]', text))
        total_chars = chinese_chars + english_chars + japanese_chars

        if total_chars == 0:
            return "zh"

        if chinese_chars / total_chars > 0.3:
            return "zh"
        elif japanese_chars / total_chars > 0.3:
            return "ja"
        elif english_chars / total_chars > 0.8:
            return "en"
        else:
            return "zh"

    @staticmethod
    def resolve_ai_voice_character(character: Optional[str], alias_map: dict, default: str) -> str:
        """解析AI Voice音色（支持别名）"""
        if not character:
            character = default

        if character.startswith("lucy-voice-"):
            return character

        if character in alias_map:
            return alias_map[character]

        if default in alias_map:
            return alias_map[default]

        return default


class UnifiedTTSAction(BaseAction):
    """统一TTS Action - LLM自动触发"""

    action_name = "unified_tts_action"
    action_description = "用语音回复（支持AI Voice/GSV2P/GPT-SoVITS多后端）"
    activation_type = ActionActivationType.LLM_JUDGE
    mode_enable = ChatMode.ALL
    parallel_action = False

    activation_keywords = ["语音", "说话", "朗读", "念一下", "读出来", "voice", "speak", "tts", "语音回复", "用语音说", "播报"]
    keyword_case_sensitive = False

    action_parameters = {
        "text": "要转换为语音的文本内容（必填）",
        "backend": "TTS后端引擎 (ai_voice/gsv2p/gpt_sovits，可选，建议省略让系统自动使用配置的默认后端)",
        "voice": "音色/风格参数（可选）"
    }

    action_require = [
        "当用户要求用语音回复时使用",
        "当回复简短问候语时使用（如早上好、晚安、你好等）",
        "当想让回复更活泼生动时可以使用",
        "注意：回复内容过长时不适合用语音",
        "注意：backend参数建议省略，系统会自动使用配置的默认后端"
    ]

    associated_types = ["text", "command"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timeout = self.get_config("general.timeout", 60)
        self.max_text_length = self.get_config("general.max_text_length", 500)

    def _check_force_trigger(self, text: str) -> bool:
        """检查是否强制触发"""
        if not self.get_config("probability.keyword_force_trigger", True):
            return False
        force_keywords = self.get_config("probability.force_keywords", ["一定要用语音", "必须语音", "语音回复我", "务必用语音"])
        return any(kw in text for kw in force_keywords)

    def _probability_check(self, text: str) -> bool:
        """概率控制检查"""
        import random

        if not self.get_config("probability.enabled", False):
            return True

        base_prob = self.get_config("probability.base_probability", 0.3)
        base_prob = max(0.0, min(1.0, base_prob))
        result = random.random() < base_prob
        logger.info(f"{self.log_prefix} 概率检查: {base_prob:.2f}, 结果={'通过' if result else '未通过'}")
        return result

    async def _execute_ai_voice(self, text: str, voice: str) -> Tuple[bool, str]:
        """执行AI Voice后端"""
        alias_map = self.get_config("ai_voice.alias_map", AI_VOICE_ALIAS_MAP)
        default_voice = self.get_config("ai_voice.default_character", "温柔妹妹")
        character = TTSUtils.resolve_ai_voice_character(voice, alias_map, default_voice)

        # 检查群聊限制 - 私聊时自动切换到 GSV2P
        chat_stream = self.chat_stream
        if not getattr(chat_stream, 'group_info', None):
            logger.info(f"{self.log_prefix} AI语音仅支持群聊,私聊自动切换到GSV2P后端")
            # 自动切换到 GSV2P 后端
            return await self._execute_gsv2p(text, voice)

        # 发送AI语音命令
        try:
            success = await self.send_command(
                command_name="AI_VOICE_SEND",
                args={"text": text, "character": character},
                storage_message=False
            )
            if success:
                logger.info(f"{self.log_prefix} AI语音发送成功 (音色: {character})")
                return True, f"成功发送AI语音 (音色: {character})"
            else:
                return False, "AI语音命令发送失败"
        except Exception as e:
            logger.error(f"{self.log_prefix} AI语音执行错误: {e}")
            return False, f"AI语音执行错误: {e}"

    async def _execute_gsv2p(self, text: str, voice: str) -> Tuple[bool, str]:
        """执行GSV2P后端"""
        api_url = self.get_config("gsv2p.api_url", "https://gsv2p.acgnai.top/v1/audio/speech")
        api_token = self.get_config("gsv2p.api_token", "")
        default_voice = self.get_config("gsv2p.default_voice", "原神-中文-派蒙_ZH")
        timeout = self.get_config("gsv2p.timeout", 30)

        if not api_token:
            return False, "GSV2P后端缺少API Token配置"

        if not voice:
            voice = default_voice

        # 构建请求参数
        request_data = {
            "model": self.get_config("gsv2p.model", "tts-v4"),
            "input": text,
            "voice": voice,
            "response_format": self.get_config("gsv2p.response_format", "mp3"),
            "speed": self.get_config("gsv2p.speed", 1),
            "other_params": {
                "text_lang": self.get_config("gsv2p.text_lang", "中英混合"),
                "prompt_lang": self.get_config("gsv2p.prompt_lang", "中文"),
                "emotion": self.get_config("gsv2p.emotion", "默认"),
                "top_k": self.get_config("gsv2p.top_k", 10),
                "top_p": self.get_config("gsv2p.top_p", 1),
                "temperature": self.get_config("gsv2p.temperature", 1),
                "text_split_method": self.get_config("gsv2p.text_split_method", "按标点符号切"),
                "batch_size": self.get_config("gsv2p.batch_size", 1),
                "batch_threshold": self.get_config("gsv2p.batch_threshold", 0.75),
                "split_bucket": self.get_config("gsv2p.split_bucket", True),
                "fragment_interval": self.get_config("gsv2p.fragment_interval", 0.3),
                "parallel_infer": self.get_config("gsv2p.parallel_infer", True),
                "repetition_penalty": self.get_config("gsv2p.repetition_penalty", 1.35),
                "sample_steps": self.get_config("gsv2p.sample_steps", 16),
                "if_sr": self.get_config("gsv2p.if_sr", False),
                "seed": self.get_config("gsv2p.seed", -1)
            }
        }

        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.post(api_url, json=request_data, headers=headers) as response:
                    if response.status == 200:
                        audio_data = await response.read()

                        if len(audio_data) < 100:
                            return False, "GSV2P音频数据过小"

                        audio_path = os.path.abspath("tts_gsv2p_output.mp3")
                        with open(audio_path, "wb") as f:
                            f.write(audio_data)

                        await self.send_custom(message_type="voiceurl", content=audio_path)
                        logger.info(f"{self.log_prefix} GSV2P语音发送成功")
                        return True, f"成功发送GSV2P语音 (音色: {voice})"
                    else:
                        error_text = await response.text()
                        return False, f"GSV2P API调用失败: {response.status}"
        except asyncio.TimeoutError:
            return False, "GSV2P API调用超时"
        except Exception as e:
            logger.error(f"{self.log_prefix} GSV2P执行错误: {e}")
            return False, f"GSV2P执行错误: {e}"

    async def _execute_gpt_sovits(self, text: str, voice_style: str) -> Tuple[bool, str]:
        """执行GPT-SoVITS后端"""
        global_server = self.get_config("gpt_sovits.server", "http://127.0.0.1:9880")
        tts_styles = self.get_config("gpt_sovits.styles", {})

        if not voice_style or voice_style not in tts_styles:
            voice_style = "default"

        if voice_style not in tts_styles:
            return False, f"GPT-SoVITS风格 '{voice_style}' 未配置"

        style_config = tts_styles[voice_style]
        refer_wav_path = style_config.get("refer_wav", "")
        prompt_text = style_config.get("prompt_text", "")
        prompt_language = style_config.get("prompt_language", "zh")

        if not refer_wav_path or not prompt_text:
            return False, f"GPT-SoVITS风格 '{voice_style}' 配置不完整"

        text_language = TTSUtils.detect_language(text)

        # 调用TTS API
        data = {
            "text": text,
            "text_lang": text_language,
            "ref_audio_path": refer_wav_path,
            "prompt_text": prompt_text,
            "prompt_lang": prompt_language
        }

        tts_url = f"{global_server.rstrip('/')}/tts"

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                async with session.post(tts_url, json=data) as response:
                    if response.status == 200:
                        audio_data = await response.read()

                        audio_path = os.path.abspath("tts_gpt_sovits_output.wav")
                        with open(audio_path, "wb") as f:
                            f.write(audio_data)

                        # 将音频文件转换为base64编码以供发送
                        import base64
                        with open(audio_path, "rb") as audio_file:
                            audio_bytes = audio_file.read()
                            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')

                        await self.send_custom(message_type="voice", content=audio_base64)
                        logger.info(f"{self.log_prefix} GPT-SoVITS语音发送成功")
                        return True, f"成功发送GPT-SoVITS语音 (风格: {voice_style})"
                    else:
                        error_info = await response.text()
                        return False, f"GPT-SoVITS API调用失败: {response.status}"
        except asyncio.TimeoutError:
            return False, "GPT-SoVITS API调用超时"
        except Exception as e:
            logger.error(f"{self.log_prefix} GPT-SoVITS执行错误: {e}")
            return False, f"GPT-SoVITS执行错误: {e}"

    async def execute(self) -> Tuple[bool, str]:
        """执行TTS语音合成"""
        try:
            text = self.action_data.get("text", "").strip()
            llm_backend = self.action_data.get("backend", "")  # LLM传入的后端
            voice = self.action_data.get("voice", "")

            if not text:
                await self.send_text("请提供要转换为语音的文本内容")
                return False, "缺少文本内容"

            # 概率检查
            force_trigger = self._check_force_trigger(text)
            if not force_trigger and not self._probability_check(text):
                logger.info(f"{self.log_prefix} 概率检查未通过，使用文字回复")
                await self.send_text(text)
                await self.store_action_info(
                    action_build_into_prompt=True,
                    action_prompt_display=f"回复了文字消息：{text}",
                    action_done=True
                )
                return True, "概率检查未通过，已发送文字回复"

            # 检查文本长度
            if len(text) > self.max_text_length * 2:
                await self.send_text(f"文本过长（{len(text)}字符），最大支持{self.max_text_length}字符")
                return False, "文本过长"

            # 清理文本
            clean_text = TTSUtils.clean_text(text, self.max_text_length)
            if not clean_text:
                await self.send_text("文本处理后为空")
                return False, "文本处理后为空"

            # 【优先使用配置文件的默认后端】
            config_backend = self.get_config("general.default_backend", "gsv2p")

            # 验证配置的后端是否有效
            valid_backends = ["ai_voice", "gsv2p", "gpt_sovits"]
            if config_backend not in valid_backends:
                logger.warning(f"{self.log_prefix} 配置的默认后端 '{config_backend}' 无效，使用 gsv2p")
                config_backend = "gsv2p"

            backend = config_backend

            # 记录后端选择来源
            if llm_backend and llm_backend != backend:
                logger.info(f"{self.log_prefix} LLM建议使用 {llm_backend}，但配置优先，使用 {backend} 后端")
            else:
                logger.info(f"{self.log_prefix} 使用配置的默认后端: {backend}")

            # 执行对应后端
            if backend == "ai_voice":
                success, msg = await self._execute_ai_voice(clean_text, voice)
            elif backend == "gsv2p":
                success, msg = await self._execute_gsv2p(clean_text, voice)
            elif backend == "gpt_sovits":
                success, msg = await self._execute_gpt_sovits(clean_text, voice)
            else:
                await self.send_text(f"未知的TTS后端: {backend}")
                return False, f"未知的TTS后端: {backend}"

            if success:
                await self.store_action_info(
                    action_build_into_prompt=True,
                    action_prompt_display=f"使用{backend}后端将文本转换为语音并发送",
                    action_done=True
                )
            else:
                await self.send_text(f"语音合成失败: {msg}")

            return success, msg

        except Exception as e:
            error_msg = str(e)
            logger.error(f"{self.log_prefix} TTS语音合成出错: {error_msg}")
            await self.send_text(f"语音合成出错: {error_msg}")
            return False, error_msg


class UnifiedTTSCommand(BaseCommand):
    """统一TTS Command - 用户手动触发"""

    command_name = "unified_tts_command"
    command_description = "将文本转换为语音，支持多种后端和音色"
    command_pattern = r"^/(?:tts|voice|gsv2p)\s+(?P<text>.+?)(?:\s+(?P<voice>\S+))?(?:\s+(?P<backend>ai_voice|gsv2p|gpt_sovits))?$"
    command_help = "将文本转换为语音。用法：/tts 你好世界 [音色] [后端]"
    command_examples = [
        "/tts 你好，世界！",
        "/tts 今天天气不错 小新",
        "/tts 试试 温柔妹妹 ai_voice",
        "/gsv2p 你好世界"
    ]
    intercept_message = True

    async def execute(self) -> Tuple[bool, str, bool]:
        """执行TTS命令"""
        try:
            text = self.matched_groups.get("text", "").strip()
            voice = self.matched_groups.get("voice", "")
            user_backend = self.matched_groups.get("backend", "")  # 用户通过命令参数指定的后端

            if not text:
                await self.send_text("请输入要转换为语音的文本内容")
                return False, "缺少文本内容", True

            # 【优先级：命令前缀 > 命令参数 > 配置文件】
            backend = ""
            backend_source = ""

            # 1. 检查命令前缀（如 /gsv2p）
            raw_text = self.message.raw_message if self.message.raw_message else self.message.processed_plain_text
            if raw_text and raw_text.startswith("/gsv2p"):
                backend = "gsv2p"
                backend_source = "命令前缀 /gsv2p"

            # 2. 检查命令参数（如 /tts text voice gpt_sovits）
            if not backend and user_backend:
                valid_backends = ["ai_voice", "gsv2p", "gpt_sovits"]
                if user_backend in valid_backends:
                    backend = user_backend
                    backend_source = f"命令参数 {user_backend}"
                else:
                    logger.warning(f"{self.log_prefix} 用户指定的后端 '{user_backend}' 无效")

            # 3. 使用配置文件的默认值
            if not backend:
                config_backend = self.get_config("general.default_backend", "gsv2p")
                valid_backends = ["ai_voice", "gsv2p", "gpt_sovits"]
                if config_backend not in valid_backends:
                    logger.warning(f"{self.log_prefix} 配置的默认后端 '{config_backend}' 无效，使用 gsv2p")
                    backend = "gsv2p"
                else:
                    backend = config_backend
                backend_source = "配置文件"

            # 清理文本
            max_length = self.get_config("general.max_text_length", 500)
            clean_text = TTSUtils.clean_text(text, max_length)

            if not clean_text:
                await self.send_text("文本处理后为空")
                return False, "文本处理后为空", True

            logger.info(f"{self.log_prefix} 执行TTS命令 (后端: {backend} [来源: {backend_source}], 音色: {voice})")

            # 执行对应后端
            if backend == "ai_voice":
                success, msg = await self._execute_ai_voice_command(clean_text, voice)
            elif backend == "gsv2p":
                success, msg = await self._execute_gsv2p_command(clean_text, voice)
            elif backend == "gpt_sovits":
                success, msg = await self._execute_gpt_sovits_command(clean_text, voice)
            else:
                await self.send_text(f"未知的TTS后端: {backend}")
                return False, f"未知的TTS后端: {backend}", True

            if not success:
                await self.send_text(f"语音合成失败: {msg}")

            return success, msg, True

        except Exception as e:
            logger.error(f"{self.log_prefix} TTS命令执行出错: {e}")
            await self.send_text(f"语音合成出错: {e}")
            return False, f"执行出错: {e}", True

    async def _execute_ai_voice_command(self, text: str, voice: str) -> Tuple[bool, str]:
        """AI Voice命令执行"""
        # 检查群聊限制 - 私聊时自动切换到 GSV2P
        if not hasattr(self.message.message_info, 'group_info') or not self.message.message_info.group_info:
            logger.info(f"{self.log_prefix} AI语音仅支持群聊,私聊自动切换到GSV2P后端")
            # 自动切换到 GSV2P 后端
            return await self._execute_gsv2p_command(text, voice)

        alias_map = self.get_config("ai_voice.alias_map", AI_VOICE_ALIAS_MAP)
        default_voice = self.get_config("ai_voice.default_character", "温柔妹妹")
        character = TTSUtils.resolve_ai_voice_character(voice, alias_map, default_voice)

        try:
            success = await self.send_command(
                command_name="AI_VOICE_SEND",
                args={"text": text, "character": character},
                storage_message=False
            )
            if success:
                return True, f"成功发送AI语音 (音色: {character})"
            else:
                return False, "AI语音命令发送失败"
        except Exception as e:
            return False, f"AI语音执行错误: {e}"

    async def _execute_gsv2p_command(self, text: str, voice: str) -> Tuple[bool, str]:
        """GSV2P命令执行"""
        api_url = self.get_config("gsv2p.api_url", "https://gsv2p.acgnai.top/v1/audio/speech")
        api_token = self.get_config("gsv2p.api_token", "")
        default_voice = self.get_config("gsv2p.default_voice", "原神-中文-派蒙_ZH")
        timeout = self.get_config("gsv2p.timeout", 30)

        if not api_token:
            return False, "GSV2P后端缺少API Token配置"

        if not voice:
            voice = default_voice

        request_data = {
            "model": self.get_config("gsv2p.model", "tts-v4"),
            "input": text,
            "voice": voice,
            "response_format": self.get_config("gsv2p.response_format", "mp3"),
            "speed": self.get_config("gsv2p.speed", 1),
            "other_params": {
                "text_lang": self.get_config("gsv2p.text_lang", "中英混合"),
                "prompt_lang": self.get_config("gsv2p.prompt_lang", "中文"),
                "emotion": self.get_config("gsv2p.emotion", "默认"),
                "top_k": self.get_config("gsv2p.top_k", 10),
                "top_p": self.get_config("gsv2p.top_p", 1),
                "temperature": self.get_config("gsv2p.temperature", 1),
                "text_split_method": self.get_config("gsv2p.text_split_method", "按标点符号切"),
                "batch_size": self.get_config("gsv2p.batch_size", 1),
                "batch_threshold": self.get_config("gsv2p.batch_threshold", 0.75),
                "split_bucket": self.get_config("gsv2p.split_bucket", True),
                "fragment_interval": self.get_config("gsv2p.fragment_interval", 0.3),
                "parallel_infer": self.get_config("gsv2p.parallel_infer", True),
                "repetition_penalty": self.get_config("gsv2p.repetition_penalty", 1.35),
                "sample_steps": self.get_config("gsv2p.sample_steps", 16),
                "if_sr": self.get_config("gsv2p.if_sr", False),
                "seed": self.get_config("gsv2p.seed", -1)
            }
        }

        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.post(api_url, json=request_data, headers=headers) as response:
                    if response.status == 200:
                        audio_data = await response.read()

                        if len(audio_data) < 100:
                            return False, "GSV2P音频数据过小"

                        audio_path = os.path.abspath("tts_gsv2p_output.mp3")
                        with open(audio_path, "wb") as f:
                            f.write(audio_data)

                        await self.send_custom(message_type="voiceurl", content=audio_path)
                        return True, f"成功发送GSV2P语音 (音色: {voice})"
                    else:
                        return False, f"GSV2P API失败: {response.status}"
        except asyncio.TimeoutError:
            return False, "GSV2P API超时"
        except Exception as e:
            return False, f"GSV2P执行错误: {e}"

    async def _execute_gpt_sovits_command(self, text: str, voice_style: str) -> Tuple[bool, str]:
        """GPT-SoVITS命令执行"""
        global_server = self.get_config("gpt_sovits.server", "http://127.0.0.1:9880")
        tts_styles = self.get_config("gpt_sovits.styles", {})
        timeout = self.get_config("general.timeout", 60)

        if not voice_style or voice_style not in tts_styles:
            voice_style = "default"

        if voice_style not in tts_styles:
            return False, f"GPT-SoVITS风格 '{voice_style}' 未配置"

        style_config = tts_styles[voice_style]
        refer_wav_path = style_config.get("refer_wav", "")
        prompt_text = style_config.get("prompt_text", "")
        prompt_language = style_config.get("prompt_language", "zh")

        if not refer_wav_path or not prompt_text:
            return False, f"GPT-SoVITS风格配置不完整"

        text_language = TTSUtils.detect_language(text)

        data = {
            "text": text,
            "text_lang": text_language,
            "ref_audio_path": refer_wav_path,
            "prompt_text": prompt_text,
            "prompt_lang": prompt_language
        }

        tts_url = f"{global_server.rstrip('/')}/tts"

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.post(tts_url, json=data) as response:
                    if response.status == 200:
                        audio_data = await response.read()

                        audio_path = os.path.abspath("tts_gpt_sovits_output.wav")
                        with open(audio_path, "wb") as f:
                            f.write(audio_data)

                        # 将音频文件转换为base64编码以供发送
                        import base64
                        with open(audio_path, "rb") as audio_file:
                            audio_bytes = audio_file.read()
                            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')

                        await self.send_custom(message_type="voice", content=audio_base64)
                        return True, f"成功发送GPT-SoVITS语音 (风格: {voice_style})"
                    else:
                        return False, f"GPT-SoVITS API失败: {response.status}"
        except asyncio.TimeoutError:
            return False, "GPT-SoVITS API超时"
        except Exception as e:
            return False, f"GPT-SoVITS执行错误: {e}"


@register_plugin
class UnifiedTTSPlugin(BasePlugin):
    """统一TTS语音合成插件 - 支持多后端的文本转语音插件"""

    plugin_name = "tts_voice_plugin"
    plugin_description = "统一TTS语音合成插件，支持AI Voice、GSV2P、GPT-SoVITS多种后端"
    plugin_version = "3.0.0"
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
        "gpt_sovits": "GPT-SoVITS后端配置"
    }

    config_schema = {
        "plugin": {
            "enabled": ConfigField(type=bool, default=True, description="是否启用插件"),
            "config_version": ConfigField(type=str, default="3.0.0", description="配置文件版本")
        },
        "general": {
            "default_backend": ConfigField(type=str, default="ai_voice", description="默认TTS后端 (ai_voice/gsv2p/gpt_sovits)"),
            "timeout": ConfigField(type=int, default=60, description="请求超时时间（秒）"),
            "max_text_length": ConfigField(type=int, default=500, description="最大文本长度")
        },
        "components": {
            "action_enabled": ConfigField(type=bool, default=True, description="是否启用Action组件"),
            "command_enabled": ConfigField(type=bool, default=True, description="是否启用Command组件")
        },
        "probability": {
            "enabled": ConfigField(type=bool, default=True, description="是否启用概率控制"),
            "base_probability": ConfigField(type=float, default=1.0, description="基础触发概率"),
            "keyword_force_trigger": ConfigField(type=bool, default=True, description="关键词强制触发"),
            "force_keywords": ConfigField(type=list, default=["一定要用语音", "必须语音", "语音回复我", "务必用语音"], description="强制触发关键词")
        },
        "ai_voice": {
            "default_character": ConfigField(type=str, default="温柔妹妹", description="默认AI语音音色"),
            "alias_map": ConfigField(type=dict, default=AI_VOICE_ALIAS_MAP, description="音色别名映射")
        },
        "gsv2p": {
            "api_url": ConfigField(type=str, default="https://gsv2p.acgnai.top/v1/audio/speech", description="GSV2P API地址"),
            "api_token": ConfigField(type=str, default="", description="API认证Token"),
            "default_voice": ConfigField(type=str, default="原神-中文-派蒙_ZH", description="默认音色"),
            "timeout": ConfigField(type=int, default=30, description="API请求超时（秒）"),
            "model": ConfigField(type=str, default="tts-v4", description="TTS模型"),
            "response_format": ConfigField(type=str, default="mp3", description="音频格式"),
            "speed": ConfigField(type=float, default=1.0, description="语音速度"),
            "text_lang": ConfigField(type=str, default="中英混合", description="文本语言"),
            "prompt_lang": ConfigField(type=str, default="中文", description="提示语言"),
            "emotion": ConfigField(type=str, default="默认", description="情感"),
            "top_k": ConfigField(type=int, default=10, description="Top-K采样"),
            "top_p": ConfigField(type=float, default=1.0, description="Top-P采样"),
            "temperature": ConfigField(type=float, default=1.0, description="温度参数"),
            "text_split_method": ConfigField(type=str, default="凑四句一切", description="文本分割方法"),
            "batch_size": ConfigField(type=int, default=1, description="批处理大小"),
            "batch_threshold": ConfigField(type=float, default=0.75, description="批处理阈值"),
            "split_bucket": ConfigField(type=bool, default=True, description="是否分桶"),
            "fragment_interval": ConfigField(type=float, default=0.3, description="片段间隔"),
            "parallel_infer": ConfigField(type=bool, default=True, description="是否并行推理"),
            "repetition_penalty": ConfigField(type=float, default=1.35, description="重复惩罚"),
            "sample_steps": ConfigField(type=int, default=16, description="采样步数"),
            "if_sr": ConfigField(type=bool, default=False, description="是否超分辨率"),
            "seed": ConfigField(type=int, default=-1, description="随机种子")
        },
        "gpt_sovits": {
            "server": ConfigField(type=str, default="http://127.0.0.1:9880", description="GPT-SoVITS服务地址"),
            "styles": ConfigField(type=dict, default={
                "default": {
                    "refer_wav": "",
                    "prompt_text": "",
                    "prompt_language": "zh",
                    "gpt_weights": "",
                    "sovits_weights": ""
                }
            }, description="语音风格配置")
        }
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        """返回插件组件列表"""
        components = []

        try:
            action_enabled = self.get_config("components.action_enabled", True)
            command_enabled = self.get_config("components.command_enabled", True)
        except AttributeError:
            action_enabled = True
            command_enabled = True

        if action_enabled:
            components.append((UnifiedTTSAction.get_action_info(), UnifiedTTSAction))

        if command_enabled:
            components.append((UnifiedTTSCommand.get_command_info(), UnifiedTTSCommand))

        return components
