from src.plugin_system import BaseAction, ActionActivationType, ChatMode
from typing import Tuple, Dict, Any
import aiohttp
import asyncio
from src.plugin_system.base.config_types import ConfigField


class TTSVoiceAction(BaseAction):
    """GPT-SoVITS 语音合成 Action 组件

    功能：将文本内容转换为语音并发送给用户，支持多风格、多语言。
    适用场景：用户明确要求语音回复、特殊情境下增强表达效果。
    """

    # === 激活控制 ===
    focus_activation_type = ActionActivationType.KEYWORD  # 专注模式下关键词激活
    normal_activation_type = ActionActivationType.KEYWORD  # 普通模式下关键词激活
    mode_enable = ChatMode.ALL  # 所有模式下可用
    parallel_action = False  # 不与其他Action并行执行

    # 关键词激活配置
    activation_keywords = [
        "语音", "说话", "朗读", "念一下", "读出来",
        "voice", "speak", "tts", "语音回复", "用语音说"
    ]
    keyword_case_sensitive = False  # 不区分大小写

    # === 基本信息 ===
    action_name = "tts_voice_action"
    action_description = "使用GPT-SoVITS将文本转换为语音并发送"

    # === 功能定义 ===
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
        """执行语音合成Action"""
        try:
            import os
            text = self.action_data.get("text", "")
            text_language = self.action_data.get("text_language", "")
            voice_style = self.action_data.get("voice_style", "default")
            if not text or len(text.strip()) == 0:
                return False, "没有提供要转换的文本内容"
            if len(text) > self.max_text_length * 2:
                return False, f"文本过长，最大支持{self.max_text_length}字符"
            clean_text = self._clean_text_for_tts(text)
            if not clean_text:
                return False, "文本处理后为空"
            if not text_language:
                text_language = self._detect_language(clean_text)
            style = self._choose_voice_style(clean_text, voice_style)
            if style not in self.tts_styles:
                style = "default"
            server_config = self.tts_styles[style]
            refer_wav_path = self.action_data.get("refer_wav_path") or server_config.get("refer_wav_path")
            prompt_text = self.action_data.get("prompt_text") or server_config.get("prompt_text")
            prompt_language = self.action_data.get("prompt_language") or server_config.get("prompt_language")

            # 只用 config.toml 中的 gpt_weights/sovits_weights
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

            audio_data = await self._call_tts_api(
                server_config=server_config,
                text=clean_text,
                text_language=text_language,
                refer_wav_path=refer_wav_path if refer_wav_path else None,
                prompt_text=prompt_text if prompt_text else None,
                prompt_language=prompt_language if prompt_language else None
            )
            # 保存为本地文件
            output_path = os.path.abspath("tts_voice_output.wav")
            with open(output_path, "wb") as f:
                f.write(audio_data)
            await self.send_voice(output_path)
            await self.store_action_info(
                action_build_into_prompt=True,
                action_prompt_display=f"将文本转换为语音并发送 (语言:{text_language}, 风格:{server_config['name']})",
                action_done=True
            )
            return True, f"成功生成并发送语音，文本长度: {len(clean_text)}字符"
        except Exception as e:
            await self.store_action_info(
                action_build_into_prompt=True,
                action_prompt_display=f"语音合成失败: {str(e)}",
                action_done=False
            )
            return False, f"语音合成失败: {str(e)}"

    async def send_voice(self, file_path: str):
        """直接发送本地音频文件路径 (自定义类型voiceurl)"""
        await self.send_custom(message_type="voiceurl", content=file_path)


from src.plugin_system import BasePlugin, register_plugin, ComponentInfo


@register_plugin
class TTSVoicePlugin(BasePlugin):
    """GPT-SoVITS 语音合成插件"""

    plugin_name = "tts_voice_plugin"
    plugin_description = "将文本转换为语音并发送，支持多风格多语言"
    plugin_version = "1.0.0"
    plugin_author = "靓仔"
    enable_plugin = True
    config_file_name = "config.toml"

    config_section_descriptions = {
        "plugin": "插件启用配置",
        "tts": "TTS语音合成相关配置",
        "tts_styles": "TTS风格参数配置（每个分组为一种风格）"
    }

    config_schema = {
        "plugin": {
            "enabled": ConfigField(type=bool, default=True, description="是否启用插件"),
            "config_version": ConfigField(type=str, default="1.0.0", description="配置文件版本"), 
        },
        "tts": {
            "timeout": ConfigField(type=int, default=30, description="TTS请求超时时间（秒）"), 
            "max_text_length": ConfigField(type=int, default=500, description="最大文本长度"), 
            "server": ConfigField(type=str, default="http://127.0.0.1:9880", description="TTS服务全局地址"), 
        },
        "tts_styles": {
            "default": {
                "refer_wav": ConfigField(type=str, default="", description="默认参考音频路径"), 
                "prompt_text": ConfigField(type=str, default="", description="默认参考文本"), 
                "prompt_language": ConfigField(type=str, default="zh", description="默认参考文本语言"), 
                "gpt_weights": ConfigField(type=str, default="", description="默认GPT模型权重路径"), 
                "sovits_weights": ConfigField(type=str, default="", description="默认SoVITS模型权重路径"), 
            }
        }
    }

    def get_plugin_components(self):
        return [
            (TTSVoiceAction.get_action_info(), TTSVoiceAction),
        ]