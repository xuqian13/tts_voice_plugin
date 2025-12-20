"""
CosyVoice后端实现
使用 ModelScope 的 Fun-CosyVoice3-0.5B Gradio API 进行语音合成
"""

import asyncio
import os
import shutil
from typing import Optional, Tuple
from .base import TTSBackendBase, TTSResult
from ..utils.file import TTSFileManager
from ..config_keys import ConfigKeys
from src.common.logger import get_logger

logger = get_logger("tts_cosyvoice")

# CosyVoice指令映射表（方言、情感、语速等）
COSYVOICE_INSTRUCT_MAP = {
    # 方言
    "广东话": "You are a helpful assistant. 请用广东话表达。<|endofprompt|>",
    "东北话": "You are a helpful assistant. 请用东北话表达。<|endofprompt|>",
    "甘肃话": "You are a helpful assistant. 请用甘肃话表达。<|endofprompt|>",
    "贵州话": "You are a helpful assistant. 请用贵州话表达。<|endofprompt|>",
    "河南话": "You are a helpful assistant. 请用河南话表达。<|endofprompt|>",
    "湖北话": "You are a helpful assistant. 请用湖北话表达。<|endofprompt|>",
    "湖南话": "You are a helpful assistant. 请用湖南话表达。<|endofprompt|>",
    "江西话": "You are a helpful assistant. 请用江西话表达。<|endofprompt|>",
    "闽南话": "You are a helpful assistant. 请用闽南话表达。<|endofprompt|>",
    "宁夏话": "You are a helpful assistant. 请用宁夏话表达。<|endofprompt|>",
    "山西话": "You are a helpful assistant. 请用山西话表达。<|endofprompt|>",
    "陕西话": "You are a helpful assistant. 请用陕西话表达。<|endofprompt|>",
    "山东话": "You are a helpful assistant. 请用山东话表达。<|endofprompt|>",
    "上海话": "You are a helpful assistant. 请用上海话表达。<|endofprompt|>",
    "四川话": "You are a helpful assistant. 请用四川话表达。<|endofprompt|>",
    "天津话": "You are a helpful assistant. 请用天津话表达。<|endofprompt|>",
    "云南话": "You are a helpful assistant. 请用云南话表达。<|endofprompt|>",

    # 音量
    "大声": "You are a helpful assistant. Please say a sentence as loudly as possible.<|endofprompt|>",
    "小声": "You are a helpful assistant. Please say a sentence in a very soft voice.<|endofprompt|>",

    # 语速
    "慢速": "You are a helpful assistant. 请用尽可能慢地语速说一句话。<|endofprompt|>",
    "快速": "You are a helpful assistant. 请用尽可能快地语速说一句话。<|endofprompt|>",

    # 情感
    "开心": "You are a helpful assistant. 请非常开心地说一句话。<|endofprompt|>",
    "伤心": "You are a helpful assistant. 请非常伤心地说一句话。<|endofprompt|>",
    "生气": "You are a helpful assistant. 请非常生气地说一句话。<|endofprompt|>",

    # 特殊风格
    "小猪佩奇": "You are a helpful assistant. 我想体验一下小猪佩奇风格，可以吗？<|endofprompt|>",
    "机器人": "You are a helpful assistant. 你可以尝试用机器人的方式解答吗？<|endofprompt|>",
}


class CosyVoiceBackend(TTSBackendBase):
    """
    CosyVoice语音后端

    使用 ModelScope 的 Fun-CosyVoice3-0.5B Gradio API 进行语音合成
    支持3秒极速复刻、自然语言控制（方言、情感、语速等）
    """

    backend_name = "cosyvoice"
    backend_description = "阿里云 CosyVoice3 API (ModelScope Gradio)"
    support_private_chat = True
    default_audio_format = "wav"

    def get_default_voice(self) -> str:
        """获取默认音色（CosyVoice 不需要预设音色）"""
        return ""

    def validate_config(self) -> Tuple[bool, str]:
        """验证配置"""
        gradio_url = self.get_config(ConfigKeys.COSYVOICE_GRADIO_URL, "")

        if not gradio_url:
            return False, "CosyVoice后端缺少必需的 gradio_url 配置"

        return True, ""

    def _resolve_instruct(self, emotion: Optional[str]) -> str:
        """
        解析情感参数为指令文本

        Args:
            emotion: 情感/方言关键词

        Returns:
            指令文本
        """
        if emotion and emotion in COSYVOICE_INSTRUCT_MAP:
            return COSYVOICE_INSTRUCT_MAP[emotion]

        # 返回默认指令（确保不为空）
        default_instruct = self.get_config(
            ConfigKeys.COSYVOICE_DEFAULT_INSTRUCT,
            "You are a helpful assistant. 请用广东话表达。<|endofprompt|>"
        )

        # 如果配置为空，强制使用广东话
        if not default_instruct or not default_instruct.strip():
            default_instruct = "You are a helpful assistant. 请用广东话表达。<|endofprompt|>"

        return default_instruct

    async def execute(
        self,
        text: str,
        voice: Optional[str] = None,
        emotion: Optional[str] = None,
        **kwargs
    ) -> TTSResult:
        """
        执行 CosyVoice 语音合成

        Args:
            text: 待转换的文本
            voice: 音色（对于CosyVoice，这个参数用于指定参考音频路径）
            emotion: 情感/方言/语速参数

        Returns:
            TTSResult
        """
        # 验证配置
        is_valid, error_msg = self.validate_config()
        if not is_valid:
            return TTSResult(False, error_msg, backend_name=self.backend_name)

        # 验证文本
        if not text or not text.strip():
            return TTSResult(False, "待合成的文本为空", backend_name=self.backend_name)

        # 获取配置
        gradio_url = self.get_config(ConfigKeys.COSYVOICE_GRADIO_URL, "")
        mode_config = self.get_config(ConfigKeys.COSYVOICE_DEFAULT_MODE, "3s极速复刻")

        # mode_checkbox_group 实际上是 Radio 组件，期望字符串而不是列表
        # 处理配置可能返回字符串或列表的情况
        if isinstance(mode_config, list):
            mode_str = mode_config[0] if mode_config else "3s极速复刻"
        else:
            mode_str = mode_config if mode_config else "3s极速复刻"

        timeout = self.get_config(ConfigKeys.COSYVOICE_TIMEOUT, 60)
        reference_audio = self.get_config(ConfigKeys.COSYVOICE_REFERENCE_AUDIO, "")
        prompt_text = self.get_config(ConfigKeys.COSYVOICE_PROMPT_TEXT, "")

        # CosyVoice 的"自然语言控制"模式实际上需要参考音频和 prompt_text
        # 如果没有配置，使用默认的参考音频
        if not reference_audio or not os.path.exists(reference_audio):
            plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            default_audio = os.path.join(plugin_dir, "test.wav")
            if os.path.exists(default_audio):
                reference_audio = default_audio
                logger.debug(f"{self.log_prefix} 使用默认参考音频: {reference_audio}")

        # 如果没有 prompt_text，使用默认文本
        if not prompt_text:
            prompt_text = "大家好，我是嘉然，今天我来为大家朗读。"
            logger.debug(f"{self.log_prefix} 使用默认 prompt_text")

        # voice 参数可以覆盖配置文件中的参考音频
        if voice and os.path.exists(voice):
            reference_audio = voice

        # 解析指令文本
        instruct_text = self._resolve_instruct(emotion)

        logger.info(
            f"{self.log_prefix} CosyVoice请求: text='{text[:50]}...' "
            f"(共{len(text)}字符), mode={mode_str}, instruct={emotion or '默认'}"
        )

        try:
            # 动态导入 gradio_client（避免全局依赖）
            try:
                from gradio_client import Client, handle_file
            except ImportError:
                logger.error(f"{self.log_prefix} gradio_client 未安装，请运行: pip install gradio_client")
                return TTSResult(
                    False,
                    "gradio_client 未安装，请运行: pip install gradio_client",
                    backend_name=self.backend_name
                )

            # 创建 Gradio 客户端（设置超时）
            try:
                import httpx
                httpx_kwargs = {"timeout": httpx.Timeout(timeout, read=timeout, write=timeout, connect=30.0)}
                client = Client(gradio_url, httpx_kwargs=httpx_kwargs)
            except Exception as e:
                logger.warning(f"{self.log_prefix} 无法设置 httpx 超时，使用默认配置: {e}")
                client = Client(gradio_url)

            # 准备参数
            logger.debug(f"{self.log_prefix} 准备参考音频: {reference_audio}")
            prompt_wav_upload = handle_file(reference_audio) if reference_audio and os.path.exists(reference_audio) else None
            logger.debug(f"{self.log_prefix} 参考音频准备完成")

            # 调用 API
            logger.info(f"{self.log_prefix} 调用 Gradio API: {gradio_url} (超时: {timeout}秒)")
            logger.debug(f"{self.log_prefix} mode参数: {mode_str} (type: {type(mode_str).__name__})")
            logger.debug(f"{self.log_prefix} prompt_text: {prompt_text[:50]}...")
            logger.debug(f"{self.log_prefix} instruct_text: {instruct_text[:50]}...")

            result = await asyncio.wait_for(
                asyncio.to_thread(
                    client.predict,
                    tts_text=text,
                    mode_checkbox_group=mode_str,
                    prompt_text=prompt_text,
                    prompt_wav_upload=prompt_wav_upload,
                    prompt_wav_record=None,
                    instruct_text=instruct_text,
                    seed=0,
                    stream=False,  # API 实际期望布尔值 False，虽然文档显示为 Literal['False']
                    api_name="/generate_audio"
                ),
                timeout=timeout
            )

            logger.info(f"{self.log_prefix} CosyVoice API 响应成功")

            # result 是生成的音频文件路径
            if not result or not os.path.exists(result):
                return TTSResult(
                    False,
                    f"CosyVoice 生成失败，未返回有效文件: {result}",
                    backend_name=self.backend_name
                )

            # 读取音频数据
            try:
                with open(result, 'rb') as f:
                    audio_data = f.read()
            except Exception as e:
                logger.error(f"{self.log_prefix} 读取音频文件失败: {e}")
                return TTSResult(
                    False,
                    f"读取音频文件失败: {e}",
                    backend_name=self.backend_name
                )

            # 验证音频数据
            is_valid, error_msg = TTSFileManager.validate_audio_data(audio_data)
            if not is_valid:
                logger.warning(f"{self.log_prefix} CosyVoice音频数据验证失败: {error_msg}")
                return TTSResult(
                    False,
                    f"CosyVoice语音{error_msg}",
                    backend_name=self.backend_name
                )

            logger.debug(
                f"{self.log_prefix} CosyVoice音频数据验证通过 "
                f"(大小: {len(audio_data)}字节)"
            )

            # 使用统一的发送方法
            audio_format = self.get_config(ConfigKeys.COSYVOICE_AUDIO_FORMAT, "wav")
            voice_info = f"模式: {mode_str}, 指令: {emotion or '默认'}"

            return await self.send_audio(
                audio_data=audio_data,
                audio_format=audio_format,
                prefix="tts_cosyvoice",
                voice_info=voice_info
            )

        except asyncio.TimeoutError:
            logger.error(f"{self.log_prefix} CosyVoice API 请求超时 (配置超时: {timeout}秒)")
            return TTSResult(
                False,
                "CosyVoice API 调用超时",
                backend_name=self.backend_name
            )
        except Exception as e:
            logger.error(f"{self.log_prefix} CosyVoice 执行异常: {e}")
            return TTSResult(
                False,
                f"CosyVoice 执行错误: {e}",
                backend_name=self.backend_name
            )
