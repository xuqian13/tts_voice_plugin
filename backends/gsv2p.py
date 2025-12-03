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

    async def execute(
        self,
        text: str,
        voice: Optional[str] = None,
        **kwargs
    ) -> TTSResult:
        """
        执行GSV2P语音合成

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

        # 构建请求参数（只使用经过验证的参数）
        request_data: Dict[str, Any] = {
            "model": self.get_config(ConfigKeys.GSV2P_MODEL, "tts-v4"),
            "input": text,
            "voice": voice,
            "response_format": self.get_config(ConfigKeys.GSV2P_RESPONSE_FORMAT, "mp3"),
            "speed": self.get_config(ConfigKeys.GSV2P_SPEED, 1),
            "other_params": {
                "text_lang": self.get_config(ConfigKeys.GSV2P_TEXT_LANG, "中英混合"),
                "emotion": self.get_config(ConfigKeys.GSV2P_EMOTION, "默认")
            }
        }

        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }

        logger.info(f"{self.log_prefix} GSV2P请求: text='{text[:50]}...', voice={voice}")
        logger.debug(f"{self.log_prefix} GSV2P完整请求参数: {json.dumps(request_data, ensure_ascii=False, indent=2)}")

        try:
            session_manager = await TTSSessionManager.get_instance()
            async with await session_manager.post(
                api_url,
                json=request_data,
                headers=headers,
                backend_name="gsv2p",
                timeout=timeout
            ) as response:
                if response.status == 200:
                    content_type = response.headers.get('Content-Type', '')
                    audio_data = await response.read()

                    logger.info(f"{self.log_prefix} GSV2P响应: Content-Type={content_type}, 数据大小={len(audio_data)}字节")

                    # 检查是否返回了JSON错误
                    if 'application/json' in content_type:
                        try:
                            error_json = json.loads(audio_data.decode('utf-8'))
                            logger.error(f"{self.log_prefix} GSV2P返回JSON错误: {error_json}")
                            error_msg = error_json.get('error', {}).get('message', str(error_json))
                            return TTSResult(False, f"GSV2P API错误: {error_msg}", backend_name=self.backend_name)
                        except Exception as parse_err:
                            logger.error(f"{self.log_prefix} 无法解析JSON错误: {parse_err}")
                            return TTSResult(
                                False,
                                f"GSV2P返回异常响应: {audio_data[:200].decode('utf-8', errors='ignore')}",
                                backend_name=self.backend_name
                            )

                    # 验证音频数据
                    is_valid, error_msg = TTSFileManager.validate_audio_data(audio_data)
                    if not is_valid:
                        logger.error(f"{self.log_prefix} GSV2P音频数据无效: {error_msg}")
                        return TTSResult(False, f"GSV2P{error_msg}", backend_name=self.backend_name)

                    # 使用统一的发送方法
                    audio_format = self.get_config(ConfigKeys.GSV2P_RESPONSE_FORMAT, "mp3")
                    return await self.send_audio(
                        audio_data=audio_data,
                        audio_format=audio_format,
                        prefix="tts_gsv2p",
                        voice_info=f"音色: {voice}"
                    )
                else:
                    error_text = await response.text()
                    logger.error(f"{self.log_prefix} GSV2P API失败[{response.status}]: {error_text}")
                    return TTSResult(
                        False,
                        f"GSV2P API调用失败: {response.status} - {error_text[:100]}",
                        backend_name=self.backend_name
                    )

        except asyncio.TimeoutError:
            return TTSResult(False, "GSV2P API调用超时", backend_name=self.backend_name)
        except Exception as e:
            logger.error(f"{self.log_prefix} GSV2P执行错误: {e}")
            return TTSResult(False, f"GSV2P执行错误: {e}", backend_name=self.backend_name)
