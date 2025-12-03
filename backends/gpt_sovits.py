"""
GPT-SoVITS 后端实现
使用本地 GPT-SoVITS 服务进行语音合成
"""

import asyncio
from typing import Optional, Dict, Any, Tuple
from .base import TTSBackendBase, TTSResult
from ..utils.text import TTSTextUtils
from ..utils.file import TTSFileManager
from ..utils.session import TTSSessionManager
from ..config_keys import ConfigKeys
from src.common.logger import get_logger

logger = get_logger("tts_gpt_sovits")


class GPTSoVITSBackend(TTSBackendBase):
    """
    GPT-SoVITS 后端

    使用本地 GPT-SoVITS 服务进行高度定制化的语音合成
    """

    backend_name = "gpt_sovits"
    backend_description = "本地GPT-SoVITS服务"
    support_private_chat = True
    default_audio_format = "wav"

    def get_default_voice(self) -> str:
        """获取默认风格"""
        return "default"

    def validate_config(self) -> Tuple[bool, str]:
        """验证配置"""
        styles: Dict[str, Any] = self.get_config(ConfigKeys.GPT_SOVITS_STYLES, {})
        if not styles or "default" not in styles:
            return False, "GPT-SoVITS未配置任何语音风格"

        default_style = styles.get("default", {})
        if not default_style.get("refer_wav") or not default_style.get("prompt_text"):
            return False, "GPT-SoVITS默认风格配置不完整（需要refer_wav和prompt_text）"

        return True, ""

    async def execute(
        self,
        text: str,
        voice: Optional[str] = None,
        **kwargs
    ) -> TTSResult:
        """
        执行GPT-SoVITS语音合成

        Args:
            text: 待转换的文本
            voice: 风格名称

        Returns:
            TTSResult
        """
        # 验证文本
        if not text or not text.strip():
            return TTSResult(False, "待合成的文本为空", backend_name=self.backend_name)

        # 获取配置
        server = self.get_config(ConfigKeys.GPT_SOVITS_SERVER, "http://127.0.0.1:9880")
        styles: Dict[str, Any] = self.get_config(ConfigKeys.GPT_SOVITS_STYLES, {})
        timeout = self.get_config(ConfigKeys.GENERAL_TIMEOUT, 60)

        # 确定使用的风格
        voice_style = voice if voice and voice in styles else "default"

        if voice_style not in styles:
            return TTSResult(
                False,
                f"GPT-SoVITS风格 '{voice_style}' 未配置",
                backend_name=self.backend_name
            )

        style_config = styles[voice_style]
        refer_wav_path = style_config.get("refer_wav", "")
        prompt_text = style_config.get("prompt_text", "")
        prompt_language = style_config.get("prompt_language", "zh")

        if not refer_wav_path or not prompt_text:
            return TTSResult(
                False,
                f"GPT-SoVITS风格 '{voice_style}' 配置不完整",
                backend_name=self.backend_name
            )

        # 检测文本语言
        text_language = TTSTextUtils.detect_language(text)

        # 构建请求数据
        data = {
            "text": text,
            "text_lang": text_language,
            "ref_audio_path": refer_wav_path,
            "prompt_text": prompt_text,
            "prompt_lang": prompt_language
        }

        tts_url = f"{server.rstrip('/')}/tts"

        logger.info(f"{self.log_prefix} GPT-SoVITS请求: text='{text[:50]}...', style={voice_style}")

        try:
            session_manager = await TTSSessionManager.get_instance()
            async with await session_manager.post(
                tts_url,
                json=data,
                backend_name="gpt_sovits",
                timeout=timeout
            ) as response:
                if response.status == 200:
                    audio_data = await response.read()

                    # 验证音频数据
                    is_valid, error_msg = TTSFileManager.validate_audio_data(audio_data)
                    if not is_valid:
                        return TTSResult(False, f"GPT-SoVITS{error_msg}", backend_name=self.backend_name)

                    # 使用统一的发送方法
                    return await self.send_audio(
                        audio_data=audio_data,
                        audio_format="wav",
                        prefix="tts_gpt_sovits",
                        voice_info=f"风格: {voice_style}"
                    )
                else:
                    error_info = await response.text()
                    logger.error(f"{self.log_prefix} GPT-SoVITS API失败[{response.status}]: {error_info[:200]}")
                    return TTSResult(
                        False,
                        f"GPT-SoVITS API调用失败: {response.status}",
                        backend_name=self.backend_name
                    )

        except asyncio.TimeoutError:
            return TTSResult(False, "GPT-SoVITS API调用超时", backend_name=self.backend_name)
        except Exception as e:
            logger.error(f"{self.log_prefix} GPT-SoVITS执行错误: {e}")
            return TTSResult(False, f"GPT-SoVITS执行错误: {e}", backend_name=self.backend_name)
