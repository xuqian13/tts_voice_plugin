"""
豆包语音后端实现
使用字节跳动豆包语音 API 进行语音合成
"""

import asyncio
import uuid
from typing import Optional, List, Dict, Tuple
from .base import TTSBackendBase, TTSResult
from .doubao_stream_parser import DoubaoStreamParser
from ..utils.file import TTSFileManager
from ..utils.session import TTSSessionManager
from ..config_keys import ConfigKeys
from src.common.logger import get_logger

logger = get_logger("tts_doubao")

# 豆包语音情感映射表（用于自动生成context_texts）
DOUBAO_EMOTION_MAP = {
    # 积极情绪
    "开心": "你的语气再欢乐一点",
    "兴奋": "用特别兴奋激动的语气说话",
    "温柔": "用温柔体贴的语气说话",
    "骄傲": "用骄傲的语气说话",
    "自信": "用自信坚定的语气说话",

    # 消极情绪
    "生气": "你得跟我互怼！就是跟我用吵架的语气对话",
    "愤怒": "用愤怒的语气说话",
    "伤心": "用特别特别痛心的语气说话",
    "失望": "用失望沮丧的语气说话",
    "委屈": "用委屈的语气说话",

    # 中性情绪
    "平静": "用平静淡定的语气说话",
    "严肃": "用严肃认真的语气说话",
    "疑惑": "用疑惑不解的语气说话",

    # 语速调整
    "慢速": "说慢一点",
    "快速": "说快一点",

    # 音量调整
    "小声": "你嗓门再小点",
    "大声": "大声一点",
}


class DoubaoBackend(TTSBackendBase):
    """
    豆包语音后端

    使用字节跳动豆包语音 API 进行高质量语音合成
    支持预置音色和复刻音色
    """

    backend_name = "doubao"
    backend_description = "字节跳动豆包语音API"
    support_private_chat = True
    default_audio_format = "mp3"

    def get_default_voice(self) -> str:
        """获取默认音色"""
        return self.get_config(ConfigKeys.DOUBAO_DEFAULT_VOICE, "zh_female_shuangkuaisisi_moon_bigtts")

    def validate_config(self) -> Tuple[bool, str]:
        """验证配置"""
        app_id = self.get_config(ConfigKeys.DOUBAO_APP_ID, "")
        access_key = self.get_config(ConfigKeys.DOUBAO_ACCESS_KEY, "")
        resource_id = self.get_config(ConfigKeys.DOUBAO_RESOURCE_ID, "")

        if not app_id or not access_key or not resource_id:
            return False, "豆包语音后端缺少必需的认证配置（app_id/access_key/resource_id）"

        return True, ""

    def _resolve_emotion(self, emotion: Optional[str]) -> Optional[List[str]]:
        """
        解析情感参数为 context_texts

        Args:
            emotion: 情感关键词

        Returns:
            context_texts 列表或 None
        """
        if emotion and emotion in DOUBAO_EMOTION_MAP:
            return [DOUBAO_EMOTION_MAP[emotion]]
        return None

    async def execute(
        self,
        text: str,
        voice: Optional[str] = None,
        emotion: Optional[str] = None,
        **kwargs
    ) -> TTSResult:
        """
        执行豆包语音合成

        Args:
            text: 待转换的文本
            voice: 音色ID
            emotion: 情感/语气参数

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
        api_url = self.get_config(ConfigKeys.DOUBAO_API_URL, "https://openspeech.bytedance.com/api/v3/tts/unidirectional")
        app_id = self.get_config(ConfigKeys.DOUBAO_APP_ID, "")
        access_key = self.get_config(ConfigKeys.DOUBAO_ACCESS_KEY, "")
        resource_id = self.get_config(ConfigKeys.DOUBAO_RESOURCE_ID, "")
        timeout = self.get_config(ConfigKeys.DOUBAO_TIMEOUT, 30)

        if not voice:
            voice = self.get_default_voice()

        # 构建请求头
        headers = {
            "Content-Type": "application/json",
            "X-Api-App-Id": app_id,
            "X-Api-Access-Key": access_key,
            "X-Api-Resource-Id": resource_id,
            "X-Api-Request-Id": str(uuid.uuid4()),
            "Accept-Encoding": "gzip, deflate"
        }

        # 构建请求体
        request_data: Dict[str, any] = {
            "req_params": {
                "text": text,
                "speaker": voice,
                "audio_params": {
                    "format": self.get_config(ConfigKeys.DOUBAO_AUDIO_FORMAT, "mp3"),
                    "sample_rate": self.get_config(ConfigKeys.DOUBAO_SAMPLE_RATE, 24000),
                    "bitrate": self.get_config(ConfigKeys.DOUBAO_BITRATE, 128000)
                }
            }
        }

        # 添加可选参数
        speed = self.get_config(ConfigKeys.DOUBAO_SPEED, None)
        if speed is not None:
            request_data["req_params"]["speed"] = speed

        volume = self.get_config(ConfigKeys.DOUBAO_VOLUME, None)
        if volume is not None:
            request_data["req_params"]["volume"] = volume

        # 处理 context_texts
        context_texts: Optional[List[str]] = None

        # 优先使用传入的emotion参数
        if emotion:
            context_texts = self._resolve_emotion(emotion)
            if context_texts:
                logger.info(f"{self.log_prefix} 使用emotion参数: {emotion} -> {context_texts[0]}")

        # 否则使用配置文件的默认值
        if not context_texts:
            context_texts = self.get_config(ConfigKeys.DOUBAO_CONTEXT_TEXTS, None)

        if context_texts:
            request_data["req_params"]["context_texts"] = context_texts

        logger.info(f"{self.log_prefix} 豆包语音请求: text='{text[:50]}...' (共{len(text)}字符), voice={voice}")

        try:
            session_manager = await TTSSessionManager.get_instance()
            async with session_manager.post(
                api_url,
                json=request_data,
                headers=headers,
                backend_name="doubao",
                timeout=timeout
            ) as response:
                logger.info(f"{self.log_prefix} 豆包API响应状态码: {response.status}")

                if response.status == 200:
                    # 使用新的流式响应解析器
                    audio_data, error_msg = await DoubaoStreamParser.parse_response(
                        response,
                        log_prefix=self.log_prefix
                    )

                    if error_msg:
                        logger.error(f"{self.log_prefix} 豆包语音解析失败: {error_msg}")
                        return TTSResult(False, error_msg, backend_name=self.backend_name)

                    # 验证音频数据
                    is_valid, error_msg = TTSFileManager.validate_audio_data(audio_data)
                    if not is_valid:
                        logger.warning(f"{self.log_prefix} 豆包音频数据验证失败: {error_msg}")
                        return TTSResult(False, f"豆包语音{error_msg}", backend_name=self.backend_name)

                    logger.debug(f"{self.log_prefix} 豆包音频数据验证通过 (大小: {len(audio_data)}字节)")

                    # 使用统一的发送方法
                    audio_format = self.get_config(ConfigKeys.DOUBAO_AUDIO_FORMAT, "mp3")
                    return await self.send_audio(
                        audio_data=audio_data,
                        audio_format=audio_format,
                        prefix="tts_doubao",
                        voice_info=f"音色: {voice}"
                    )
                else:
                    error_text = await response.text()
                    logger.error(f"{self.log_prefix} 豆包API请求失败[{response.status}]: {error_text[:200]}")
                    return TTSResult(
                        False,
                        f"豆包语音API调用失败: {response.status} - {error_text[:100]}",
                        backend_name=self.backend_name
                    )

        except asyncio.TimeoutError:
            logger.error(f"{self.log_prefix} 豆包API请求超时 (配置超时: {timeout}秒)")
            return TTSResult(False, "豆包语音API调用超时", backend_name=self.backend_name)
        except Exception as e:
            logger.error(f"{self.log_prefix} 豆包语音执行异常: {e}")
            return TTSResult(False, f"豆包语音执行错误: {e}", backend_name=self.backend_name)
