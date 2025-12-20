"""
GSV2P 后端实现
使用 GSV2P 云端 API 进行语音合成
"""

import asyncio
import json
from typing import Optional, Dict, Any, Tuple
from .base import TTSBackendBase, TTSResult
from ..utils.file import TTSFileManager
from ..utils.session import TTSSessionManager
from ..config_keys import ConfigKeys
from src.common.logger import get_logger

logger = get_logger("tts_gsv2p")

# 重试配置
MAX_RETRIES = 5  # 最大重试次数
RETRY_DELAY = 3.0  # 重试间隔（秒）


class GSV2PBackend(TTSBackendBase):
    """
    GSV2P 后端

    使用 GSV2P 云端 API 进行高质量语音合成
    """

    backend_name = "gsv2p"
    backend_description = "GSV2P云端API语音合成"
    support_private_chat = True
    default_audio_format = "mp3"

    def get_default_voice(self) -> str:
        """获取默认音色"""
        return self.get_config(ConfigKeys.GSV2P_DEFAULT_VOICE, "原神-中文-派蒙_ZH")

    def validate_config(self) -> Tuple[bool, str]:
        """验证配置"""
        api_token = self.get_config(ConfigKeys.GSV2P_API_TOKEN, "")
        if not api_token:
            return False, "GSV2P后端缺少API Token配置"
        return True, ""

    async def _make_request(
        self,
        api_url: str,
        request_data: Dict[str, Any],
        headers: Dict[str, str],
        timeout: int
    ) -> Tuple[bool, Any, str]:
        """
        发送单次API请求

        Returns:
            (成功标志, 音频数据或None, 错误信息)
        """
        session_manager = await TTSSessionManager.get_instance()
        async with session_manager.post(
            api_url,
            json=request_data,
            headers=headers,
            backend_name="gsv2p",
            timeout=timeout
        ) as response:
            if response.status == 200:
                content_type = response.headers.get('Content-Type', '')
                audio_data = await response.read()

                # 检查是否返回了JSON错误（服务端不稳定时会返回参数错误）
                if 'application/json' in content_type:
                    try:
                        error_json = json.loads(audio_data.decode('utf-8'))
                        error_msg = error_json.get('error', {}).get('message', str(error_json))
                        # 参数错误通常是服务端临时问题，可以重试
                        return False, None, f"API返回错误: {error_msg}"
                    except Exception:
                        return False, None, "API返回异常响应"

                # 验证音频数据
                is_valid, error_msg = TTSFileManager.validate_audio_data(audio_data)
                if not is_valid:
                    return False, None, f"音频数据无效: {error_msg}"

                return True, audio_data, ""
            else:
                error_text = await response.text()
                return False, None, f"API调用失败: {response.status} - {error_text[:100]}"

    async def execute(
        self,
        text: str,
        voice: Optional[str] = None,
        **kwargs
    ) -> TTSResult:
        """
        执行GSV2P语音合成（带重试机制）

        Args:
            text: 待转换的文本
            voice: 音色名称

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
        api_url = self.get_config(ConfigKeys.GSV2P_API_URL, "https://gsv2p.acgnai.top/v1/audio/speech")
        api_token = self.get_config(ConfigKeys.GSV2P_API_TOKEN, "")
        timeout = self.get_config(ConfigKeys.GSV2P_TIMEOUT, 30)

        if not voice:
            voice = self.get_default_voice()

        # 构建请求参数（注意：other_params 已被 API 废弃，不再支持）
        request_data: Dict[str, Any] = {
            "model": self.get_config(ConfigKeys.GSV2P_MODEL, "tts-v4"),
            "input": text,
            "voice": voice,
            "response_format": self.get_config(ConfigKeys.GSV2P_RESPONSE_FORMAT, "mp3"),
            "speed": self.get_config(ConfigKeys.GSV2P_SPEED, 1)
        }

        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }

        logger.info(f"{self.log_prefix} GSV2P请求: text='{text[:50]}...', voice={voice}")
        logger.debug(f"{self.log_prefix} GSV2P完整请求参数: {json.dumps(request_data, ensure_ascii=False, indent=2)}")

        last_error = ""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                success, audio_data, error_msg = await self._make_request(
                    api_url, request_data, headers, timeout
                )

                if success and audio_data:
                    if attempt > 1:
                        logger.info(f"{self.log_prefix} GSV2P第{attempt}次重试成功")

                    logger.info(f"{self.log_prefix} GSV2P响应: 数据大小={len(audio_data)}字节")

                    # 使用统一的发送方法
                    audio_format = self.get_config(ConfigKeys.GSV2P_RESPONSE_FORMAT, "mp3")
                    return await self.send_audio(
                        audio_data=audio_data,
                        audio_format=audio_format,
                        prefix="tts_gsv2p",
                        voice_info=f"音色: {voice}"
                    )
                else:
                    last_error = error_msg
                    if attempt < MAX_RETRIES:
                        logger.warning(f"{self.log_prefix} GSV2P请求失败 ({error_msg}), {RETRY_DELAY}秒后重试 (尝试 {attempt}/{MAX_RETRIES})")
                        await asyncio.sleep(RETRY_DELAY)
                    else:
                        logger.error(f"{self.log_prefix} GSV2P请求失败，已达最大重试次数: {error_msg}")

            except asyncio.TimeoutError:
                last_error = "API调用超时"
                if attempt < MAX_RETRIES:
                    logger.warning(f"{self.log_prefix} GSV2P超时, {RETRY_DELAY}秒后重试 (尝试 {attempt}/{MAX_RETRIES})")
                    await asyncio.sleep(RETRY_DELAY)
                else:
                    logger.error(f"{self.log_prefix} GSV2P超时，已达最大重试次数")

            except Exception as e:
                last_error = str(e)
                logger.error(f"{self.log_prefix} GSV2P执行错误: {e}")
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY)
                else:
                    break

        return TTSResult(False, f"GSV2P {last_error} (已重试{MAX_RETRIES}次)", backend_name=self.backend_name)
