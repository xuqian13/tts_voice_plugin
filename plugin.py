"""
TTS Voice 插件

基于 GPT-SoVITS 的文本转语音插件，支持多种语言和多风格语音合成。

功能特性：
- 支持中文、英文、日文等多种语言
- 多种语音风格配置
- Action自动触发和Command手动触发两种模式
- 支持配置文件自定义设置
- 智能语言检测和文本清理

使用方法：
- Action触发：发送包含"语音"、"说话"等关键词的消息
- Command触发：/tts 你好世界 [风格]

API接口：基于本地GPT-SoVITS服务
"""

from typing import List, Tuple, Type, Optional, Dict, Any
import aiohttp
import asyncio
import os
import re
import tempfile
from src.common.logger import get_logger
from src.plugin_system.base.base_plugin import BasePlugin
from src.plugin_system.apis.plugin_register_api import register_plugin
from src.plugin_system.base.base_action import BaseAction, ActionActivationType, ChatMode
from src.plugin_system.base.base_command import BaseCommand
from src.plugin_system.base.component_types import ComponentInfo
from src.plugin_system.base.config_types import ConfigField

logger = get_logger("tts_voice_plugin")

# ===== Action组件 =====
class TTSVoiceAction(BaseAction):
    """GPT-SoVITS 语音合成 Action 组件 - 智能语音合成"""

    action_name = "tts_voice_action"
    action_description = "使用GPT-SoVITS将文本转换为语音并发送"

    # 激活设置
    focus_activation_type = ActionActivationType.KEYWORD
    normal_activation_type = ActionActivationType.KEYWORD
    mode_enable = ChatMode.ALL
    parallel_action = False

    # 关键词激活
    activation_keywords = [
        "语音", "说话", "朗读", "念一下", "读出来",
        "voice", "speak", "tts", "语音回复", "用语音说"
    ]
    keyword_case_sensitive = False

    # Action参数
    action_parameters = {
        "text": "要转换为语音的文本内容",
        "text_language": "文本语言 (zh/en/ja)",
        "refer_wav_path": "参考音频路径 (可选)",
        "prompt_text": "参考音频文本 (可选)",
        "prompt_language": "参考音频语言 (可选)",
        "voice_style": "语音风格选择 (默认/温柔/活泼等)"
    }
    action_require = [
        "用户明确要求语音回复时使用",
        "文本内容较长且适合朗读时考虑使用",
        "特殊场景需要增强表达效果时使用",
        "当表达内容更适合用语音而不是文字传达时使用",
        "确保文本内容适合语音表达"
    ]
    associated_types = ["text"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 缓存TTS风格配置（从 tts_styles 读取）
        self.tts_styles = self._load_tts_styles()
        self.timeout = self.get_config("tts.timeout", 60)
        self.max_text_length = self.get_config("tts.max_text_length", 500)

    def _load_tts_styles(self) -> Dict[str, Dict[str, Any]]:
        """加载 TTS 风格配置，读取 tts_styles 下所有分组，server 统一用全局 tts.server"""
        styles = {}
        global_server = self.get_config("tts.server", "http://127.0.0.1:9880")
        tts_styles = self.get_config("tts_styles", None)
        if isinstance(tts_styles, dict):
            for style_name, style_cfg in tts_styles.items():
                styles[style_name] = {
                    "url": global_server,
                    "name": style_cfg.get("name", style_name),
                    "refer_wav_path": style_cfg.get("refer_wav", ""),
                    "prompt_text": style_cfg.get("prompt_text", ""),
                    "prompt_language": style_cfg.get("prompt_language", "zh"),
                    "gpt_weights": style_cfg.get("gpt_weights", None),
                    "sovits_weights": style_cfg.get("sovits_weights", None)
                }
        return styles

    def _detect_language(self, text: str) -> str:
        """智能检测文本语言"""
        import re
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

    def _clean_text_for_tts(self, text: str) -> str:
        """清理文本，使其更适合TTS"""
        import re
        text = re.sub(r'[^\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ffa-zA-Z0-9\s，。！？、；：（）【】"\'.,!?;:()\[\]`-]', '', text)
        replacements = {
            'www': '哈哈哈',
            'hhh': '哈哈',
            '233': '哈哈',
            '666': '厉害',
            '88': '拜拜',
            '...': '。',
            '……': '。'
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        if len(text) > self.max_text_length:
            text = text[:self.max_text_length] + "。"
        return text.strip()

    def _choose_voice_style(self, text: str, style_hint: str = None) -> str:
        """根据 style_hint 返回不同风格，若无匹配则返回 default"""
        if style_hint:
            import re
            style_en = style_hint.strip().lower()
            print(f"当前风格: {style_en}")
            print(f"可用风格: {list(self.tts_styles.keys())}")
            if style_en in self.tts_styles:
                return style_en
        return "default"

    async def _call_tts_api(self, server_config: Dict, text: str, text_language: str,
                           refer_wav_path: str = None, prompt_text: str = None,
                           prompt_language: str = None) -> bytes:
        """调用TTS API，自动拼接 /tts"""
        try:
            data = {
                "text": text,
                "text_lang": text_language
            }
            if refer_wav_path:
                data["ref_audio_path"] = refer_wav_path
            if prompt_text:
                data["prompt_text"] = prompt_text
            if prompt_language:
                data["prompt_lang"] = prompt_language
            # 自动拼接 /tts
            base_url = server_config["url"].rstrip("/")
            tts_url = base_url if base_url.endswith("/tts") else base_url + "/tts"
            debug_msg = f"TTS API URL: {tts_url}\nTTS API JSON: {data}"
            print(debug_msg)
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                async with session.post(tts_url, json=data) as response:
                    if response.status == 200:
                        audio_data = await response.read()
                        return audio_data
                    else:
                        error_info = await response.text()
                        raise Exception(f"TTS API调用失败: {response.status} - {error_info}")
        except asyncio.TimeoutError:
            raise Exception("TTS服务请求超时")
        except Exception as e:
            raise Exception(f"TTS API调用异常: {str(e)}")

    async def execute(self) -> Tuple[bool, str]:
        """执行GPT-SoVITS语音合成"""
        try:
            # 获取参数
            text = self.action_data.get("text", "").strip()
            text_language = self.action_data.get("text_language", "")
            voice_style = self.action_data.get("voice_style", "default")

            if not text:
                await self.send_text("❌ 请提供要转换为语音的文本内容")
                return False, "缺少文本内容"

            if len(text) > self.max_text_length * 2:
                await self.send_text(f"❌ 文本过长，最大支持{self.max_text_length}字符")
                return False, f"文本过长，最大支持{self.max_text_length}字符"

            # 清理和处理文本
            clean_text = self._clean_text_for_tts(text)
            if not clean_text:
                await self.send_text("❌ 文本处理后为空")
                return False, "文本处理后为空"

            # 检测语言
            if not text_language:
                text_language = self._detect_language(clean_text)

            # 选择语音风格
            style = self._choose_voice_style(clean_text, voice_style)
            if style not in self.tts_styles:
                style = "default"

            server_config = self.tts_styles[style]
            refer_wav_path = self.action_data.get("refer_wav_path") or server_config.get("refer_wav_path")
            prompt_text = self.action_data.get("prompt_text") or server_config.get("prompt_text")
            prompt_language = self.action_data.get("prompt_language") or server_config.get("prompt_language")

            logger.info(f"{self.log_prefix} 开始GPT-SoVITS语音合成，文本：{clean_text[:50]}..., 风格：{style}")

            # 切换模型权重（如果配置了）
            gpt_weights = server_config.get("gpt_weights")
            sovits_weights = server_config.get("sovits_weights")

            async def switch_model(weight_url, param_name):
                if weight_url:
                    api_url = None
                    if param_name == "gpt_weights":
                        api_url = f"{server_config['url'].rstrip('/')}/set_gpt_weights"
                    elif param_name == "sovits_weights":
                        api_url = f"{server_config['url'].rstrip('/')}/set_sovits_weights"
                    if api_url:
                        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                            async with session.get(api_url, params={"weights_path": weight_url}) as resp:
                                if resp.status != 200:
                                    try:
                                        err = await resp.json()
                                        msg = err.get("message", "")
                                    except Exception:
                                        msg = await resp.text()
                                    raise Exception(f"切换模型失败: {param_name} {weight_url} {msg}")

            await switch_model(gpt_weights, "gpt_weights")
            await switch_model(sovits_weights, "sovits_weights")

            # 调用TTS API生成语音
            audio_data = await self._call_tts_api(
                server_config=server_config,
                text=clean_text,
                text_language=text_language,
                refer_wav_path=refer_wav_path if refer_wav_path else None,
                prompt_text=prompt_text if prompt_text else None,
                prompt_language=prompt_language if prompt_language else None
            )

            if audio_data:
                # 保存音频文件
                output_path = os.path.abspath("tts_voice_output.wav")
                with open(output_path, "wb") as f:
                    f.write(audio_data)

                # 发送语音文件
                await self.send_custom(message_type="voiceurl", content=output_path)
                logger.info(f"{self.log_prefix} GPT-SoVITS语音发送成功")

                await self.store_action_info(
                    action_build_into_prompt=True,
                    action_prompt_display=f"将文本转换为语音并发送 (语言:{text_language}, 风格:{server_config.get('name', style)})",
                    action_done=True
                )
                return True, f"成功生成并发送语音，文本长度: {len(clean_text)}字符"
            else:
                await self.send_text("❌ 语音合成失败，请稍后重试")
                return False, "语音合成失败"

        except Exception as e:
            logger.error(f"{self.log_prefix} GPT-SoVITS语音合成出错: {e}")
            await self.send_text(f"❌ 语音合成出错: {e}")
            await self.store_action_info(
                action_build_into_prompt=True,
                action_prompt_display=f"语音合成失败: {str(e)}",
                action_done=False
            )
            return False, f"语音合成出错: {str(e)}"

# ===== 插件注册 =====


@register_plugin
class TTSVoicePlugin(BasePlugin):
    """GPT-SoVITS 语音合成插件 - 基于GPT-SoVITS的文本转语音插件"""

    plugin_name = "tts_voice_plugin"
    plugin_description = "基于GPT-SoVITS的文本转语音插件，支持多种语言和多风格语音合成"
    plugin_version = "2.0.0"
    plugin_author = "靓仔"
    enable_plugin = True
    config_file_name = "config.toml"
    dependencies = []  # 插件依赖列表
    python_dependencies = ["aiohttp"]  # Python包依赖列表

    # 配置节描述
    config_section_descriptions = {
        "plugin": "插件基本配置",
        "components": "组件启用控制",
        "tts": "TTS语音合成相关配置",
        "tts_styles": "TTS风格参数配置（每个分组为一种风格）"
    }

    # 配置Schema定义
    config_schema = {
        "plugin": {
            "enabled": ConfigField(type=bool, default=True, description="是否启用插件"),
            "config_version": ConfigField(type=str, default="2.0.0", description="配置文件版本")
        },
        "components": {
            "action_enabled": ConfigField(type=bool, default=True, description="是否启用Action组件")
        },
        "tts": {
            "timeout": ConfigField(type=int, default=60, description="TTS请求超时时间（秒）"),
            "max_text_length": ConfigField(type=int, default=1000, description="最大文本长度"),
            "server": ConfigField(type=str, default="http://127.0.0.1:9880", description="TTS服务全局地址")
        },
        "tts_styles": {
            "default": {
                "refer_wav": ConfigField(type=str, default="", description="默认参考音频路径"),
                "prompt_text": ConfigField(type=str, default="", description="默认参考文本"),
                "prompt_language": ConfigField(type=str, default="zh", description="默认参考文本语言"),
                "gpt_weights": ConfigField(type=str, default="", description="默认GPT模型权重路径"),
                "sovits_weights": ConfigField(type=str, default="", description="默认SoVITS模型权重路径")
            }
        }
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        """返回插件包含的组件列表"""
        components = []

        # 根据配置决定是否启用组件（如果get_config方法不可用，则默认启用）
        try:
            action_enabled = self.get_config("components.action_enabled", True)
        except AttributeError:
            # 如果get_config方法不存在，默认启用所有组件
            action_enabled = True

        if action_enabled:
            components.append((TTSVoiceAction.get_action_info(), TTSVoiceAction))

        return components