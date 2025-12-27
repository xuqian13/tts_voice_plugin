"""
GPT-SoVITS 后端实现
使用本地 GPT-SoVITS 服务进行语音合成
"""

import asyncio
from typing import Optional, Dict, Any, Tuple, ClassVar
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
    支持动态切换 GPT 和 SoVITS 模型权重
    """

    backend_name = "gpt_sovits"
    backend_description = "本地GPT-SoVITS服务"
    support_private_chat = True
    default_audio_format = "wav"

    # 类变量：记录当前加载的模型路径，避免重复切换
    _current_gpt_weights: ClassVar[Optional[str]] = None
    _current_sovits_weights: ClassVar[Optional[str]] = None

    def get_default_voice(self) -> str:
        """获取默认风格"""
        return "default"

    async def _switch_model(
        self,
        server: str,
        gpt_weights: Optional[str],
        sovits_weights: Optional[str],
        timeout: int
    ) -> Tuple[bool, str]:
        """
        切换 GPT-SoVITS 模型权重

        Args:
            server: 服务器地址
            gpt_weights: GPT 模型权重路径
            sovits_weights: SoVITS 模型权重路径
            timeout: 超时时间

        Returns:
            (success, error_message)
        """
        session_manager = await TTSSessionManager.get_instance()

        # 切换 GPT 权重
        if gpt_weights and gpt_weights != GPTSoVITSBackend._current_gpt_weights:
            gpt_url = f"{server.rstrip('/')}/set_gpt_weights?weights_path={gpt_weights}"
            logger.info(f"{self.log_prefix} 切换GPT模型: {gpt_weights}")

            try:
                async with session_manager.get(
                    gpt_url,
                    backend_name="gpt_sovits",
                    timeout=timeout
                ) as response:
                    if response.status == 200:
                        GPTSoVITSBackend._current_gpt_weights = gpt_weights
                        logger.info(f"{self.log_prefix} GPT模型切换成功")
                    else:
                        error_text = await response.text()
                        return False, f"GPT模型切换失败: {error_text}"
            except Exception as e:
                return False, f"GPT模型切换异常: {e}"

        # 切换 SoVITS 权重
        if sovits_weights and sovits_weights != GPTSoVITSBackend._current_sovits_weights:
            sovits_url = f"{server.rstrip('/')}/set_sovits_weights?weights_path={sovits_weights}"
            logger.info(f"{self.log_prefix} 切换SoVITS模型: {sovits_weights}")

            try:
                async with session_manager.get(
                    sovits_url,
                    backend_name="gpt_sovits",
                    timeout=timeout
                ) as response:
                    if response.status == 200:
                        GPTSoVITSBackend._current_sovits_weights = sovits_weights
                        logger.info(f"{self.log_prefix} SoVITS模型切换成功")
                    else:
                        error_text = await response.text()
                        return False, f"SoVITS模型切换失败: {error_text}"
            except Exception as e:
                return False, f"SoVITS模型切换异常: {e}"

        return True, ""

    def _normalize_styles_config(self, styles_config: Any) -> Dict[str, Any]:
        """
        规范化风格配置格式

        支持两种格式：
        1. 旧格式（字典）: {"default": {...}, "happy": {...}}
        2. 新格式（数组）: [{"name": "default", ...}, {"name": "happy", ...}]

        统一转换为字典格式供内部使用
        """
        # 如果是字典格式（旧格式），直接返回
        if isinstance(styles_config, dict):
            return styles_config

        # 如果是数组格式（新格式），转换为字典
        if isinstance(styles_config, list):
            result = {}
            for style in styles_config:
                if isinstance(style, dict) and "name" in style:
                    style_name = style["name"]
                    # 复制配置，移除 name 字段
                    style_data = {k: v for k, v in style.items() if k != "name"}
                    result[style_name] = style_data
            return result

        # 其他情况返回空字典
        return {}

    def validate_config(self) -> Tuple[bool, str]:
        """验证配置"""
        styles_raw = self.get_config(ConfigKeys.GPT_SOVITS_STYLES, {})
        styles = self._normalize_styles_config(styles_raw)

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
        styles_raw = self.get_config(ConfigKeys.GPT_SOVITS_STYLES, {})
        styles = self._normalize_styles_config(styles_raw)
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
        gpt_weights = style_config.get("gpt_weights")
        sovits_weights = style_config.get("sovits_weights")

        if not refer_wav_path or not prompt_text:
            return TTSResult(
                False,
                f"GPT-SoVITS风格 '{voice_style}' 配置不完整",
                backend_name=self.backend_name
            )

        # 如果配置了模型权重，先切换模型
        if gpt_weights or sovits_weights:
            switch_success, switch_error = await self._switch_model(
                server, gpt_weights, sovits_weights, timeout
            )
            if not switch_success:
                return TTSResult(False, switch_error, backend_name=self.backend_name)

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
            async with session_manager.post(
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
