"""
MiniMax TTS 后端实现
使用 MiniMax T2A V2 API (MiniMax语音合成) 进行语音合成
支持多情感控制、语速/音量/音调调节、自定义音色 ID
"""

import asyncio
import json
import logging
from typing import Optional, Tuple, Dict, Any

from .base import TTSBackendBase, TTSResult
from ..utils.file import TTSFileManager
from ..utils.session import TTSSessionManager
from ..config_keys import ConfigKeys

logger = logging.getLogger("plugin.tts_voice_plugin.minimax")

# MiniMax 情感映射表（中文关键词 → API 情感参数）
MINIMAX_EMOTION_MAP: Dict[str, str] = {
    # 积极情绪
    "开心": "happy",
    "高兴": "happy",
    "兴奋": "happy",
    # 消极情绪
    "伤心": "sad",
    "难过": "sad",
    "失望": "sad",
    "委屈": "sad",
    "生气": "angry",
    "愤怒": "angry",
    # 恐惧/厌恶
    "害怕": "fearful",
    "恐惧": "fearful",
    "厌恶": "disgusted",
    "恶心": "disgusted",
    # 惊讶
    "惊讶": "surprised",
    "震惊": "surprised",
    # 中性
    "平静": "calm",
    "冷静": "calm",
    "严肃": "calm",
    # 流畅/自然
    "流畅": "fluent",
    "自然": "fluent",
    # 耳语
    "耳语": "whisper",
    "低语": "whisper",
    "轻声": "whisper",
    "悄悄话": "whisper",
}

# API 合法英文情感值集合
MINIMAX_VALID_EMOTIONS = {
    "happy", "sad", "angry", "fearful",
    "disgusted", "surprised", "calm", "fluent", "whisper",
}

# MiniMax API 错误码 → 中文错误消息映射
MINIMAX_ERROR_MAP: Dict[int, str] = {
    1000: "未知错误",
    1001: "请求超时",
    1002: "触发限流，请稍后重试",
    1004: "鉴权失败，请检查 API Key 是否正确",
    1039: "TPM 速率限制，请稍后重试",
    1042: "文本包含非法字符",
    2013: "参数错误",
}


class MiniMaxBackend(TTSBackendBase):
    """
    MiniMax TTS 后端

    使用 MiniMax 语音合成 API (T2A V2)，支持:
    - 多种系统音色和自定义音色 ID
    - 9 种情感参数控制
    - 语速/音量/音调细粒度调节
    - 多种音频格式与采样率
    """

    backend_name = "minimax"
    backend_description = "minimax TTS API"
    support_private_chat = True
    default_audio_format = "mp3"

    def get_default_voice(self) -> str:
        """获取默认音色 ID（用户可在配置中自定义为其他系统音色或复刻音色）"""
        return self.get_config(ConfigKeys.MINIMAX_DEFAULT_VOICE, "male-qn-qingse")

    def validate_config(self) -> Tuple[bool, str]:
        """验证配置"""
        api_key = self.get_config(ConfigKeys.MINIMAX_API_KEY, "")
        if not api_key:
            return False, "minimax TTS 后端缺少 api_key 配置"
        return True, ""

    def _resolve_emotion(self, emotion: Optional[str]) -> Optional[str]:
        """
        解析情感参数

        Args:
            emotion: 中文情感关键词或英文 API 情感值

        Returns:
            合法英文情感值，未匹配返回 None
        """
        if not emotion:
            return None

        # 中文关键词映射
        if emotion in MINIMAX_EMOTION_MAP:
            return MINIMAX_EMOTION_MAP[emotion]

        # 已为合法英文值则原样使用
        if emotion in MINIMAX_VALID_EMOTIONS:
            return emotion

        logger.warning(
            "%s 未识别的情感参数: %s（忽略，不影响合成）",
            self.log_prefix, emotion,
        )
        return None

    async def execute(
        self,
        text: str,
        voice: Optional[str] = None,
        emotion: Optional[str] = None,
        **kwargs
    ) -> TTSResult:
        """
        执行 minimax 语音合成

        API 请求格式:
        - POST https://api-bj.minimaxi.com/v1/t2a_v2
        - Authorization: Bearer <api_key>
        - 请求体包含 model, text, voice_setting, audio_setting
        - 响应: data.audio 为 hex 编码音频

        Args:
            text: 待转换的文本
            voice: 音色 ID（留空使用配置中的 default_voice）
            emotion: 情感/语气参数（中文关键词或英文值）

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
        api_url = self.get_config(
            ConfigKeys.MINIMAX_API_URL,
            "https://api-bj.minimaxi.com/v1/t2a_v2",
        )
        api_key = self.get_config(ConfigKeys.MINIMAX_API_KEY, "")
        model = self.get_config(ConfigKeys.MINIMAX_MODEL, "speech-2.6-hd")
        audio_format = self.get_config(ConfigKeys.MINIMAX_AUDIO_FORMAT, "mp3")
        timeout = self.get_config(ConfigKeys.MINIMAX_TIMEOUT, 30)
        sample_rate = self.get_config(ConfigKeys.MINIMAX_SAMPLE_RATE, 32000)
        bitrate = self.get_config(ConfigKeys.MINIMAX_BITRATE, 128000)
        channel = self.get_config(ConfigKeys.MINIMAX_CHANNEL, 1)
        speed = self.get_config(ConfigKeys.MINIMAX_SPEED, 1.0)
        volume = self.get_config(ConfigKeys.MINIMAX_VOLUME, 1.0)
        pitch = self.get_config(ConfigKeys.MINIMAX_PITCH, 0)

        # 决定 voice_id：优先用传入参数，否则用配置默认值
        voice_id = voice if voice else self.get_default_voice()

        # 解析情感
        resolved_emotion = self._resolve_emotion(emotion)
        if emotion and resolved_emotion:
            logger.info(
                "%s 使用emotion参数: %s -> %s",
                self.log_prefix, emotion, resolved_emotion,
            )

        # 构建 voice_setting
        voice_setting: Dict[str, Any] = {
            "voice_id": voice_id,
            "speed": speed,
            "vol": volume,
            "pitch": pitch,
        }
        if resolved_emotion:
            voice_setting["emotion"] = resolved_emotion

        # 构建 audio_setting
        audio_setting: Dict[str, Any] = {
            "sample_rate": sample_rate,
            "bitrate": bitrate,
            "format": audio_format,
            "channel": channel,
        }

        # 构建请求体
        request_data: Dict[str, Any] = {
            "model": model,
            "text": text,
            "stream": False,
            "voice_setting": voice_setting,
            "audio_setting": audio_setting,
            "output_format": "hex",
        }

        # 请求头
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        logger.info(
            "%s minimax请求: text='%s...' (共%d字符), voice=%s, emotion=%s, model=%s",
            self.log_prefix, text[:50], len(text), voice_id, resolved_emotion or "无", model,
        )
        logger.debug(
            "%s minimax完整请求参数: %s",
            self.log_prefix,
            json.dumps(request_data, ensure_ascii=False, indent=2),
        )

        try:
            session_manager = await TTSSessionManager.get_instance()
            async with session_manager.post(
                api_url,
                json=request_data,
                headers=headers,
                backend_name="minimax",
                timeout=timeout,
            ) as response:
                logger.info(f"{self.log_prefix} minimax API响应状态码: {response.status}")

                if response.status == 200:
                    response_data = await response.json()

                    # 检查业务状态码
                    base_resp = response_data.get("base_resp") or {}
                    status_code = base_resp.get("status_code", -1)
                    if status_code != 0:
                        error_msg = MINIMAX_ERROR_MAP.get(
                            status_code,
                            base_resp.get("status_msg") or f"API返回错误码: {status_code}",
                        )
                        logger.error(
                            "%s minimax API业务错误[%d]: %s",
                            self.log_prefix, status_code, error_msg,
                        )
                        return TTSResult(
                            False,
                            f"minimax语音{error_msg}",
                            backend_name=self.backend_name,
                        )

                    # 提取音频 hex 数据
                    data = response_data.get("data") or {}
                    audio_hex = data.get("audio")
                    if not audio_hex:
                        logger.error(
                            "%s minimax响应缺少音频数据: %s",
                            self.log_prefix,
                            json.dumps(response_data, ensure_ascii=False)[:300],
                        )
                        return TTSResult(
                            False,
                            "minimax响应缺少音频数据",
                            backend_name=self.backend_name,
                        )

                    # hex 解码为音频字节
                    try:
                        audio_data = bytes.fromhex(audio_hex)
                    except (ValueError, TypeError) as e:
                        logger.error(f"{self.log_prefix} minimax音频hex解码失败: {e}")
                        return TTSResult(
                            False,
                            f"minimax音频解码失败: {e}",
                            backend_name=self.backend_name,
                        )

                    # 验证音频数据
                    is_valid, error_msg = TTSFileManager.validate_audio_data(audio_data)
                    if not is_valid:
                        logger.warning(f"{self.log_prefix} minimax音频数据验证失败: {error_msg}")
                        return TTSResult(
                            False,
                            f"minimax语音{error_msg}",
                            backend_name=self.backend_name,
                        )

                    logger.debug(
                        f"{self.log_prefix} minimax音频数据验证通过 (大小: {len(audio_data)}字节)"
                    )

                    # 发送音频
                    voice_info = f"音色: {voice_id}"
                    if resolved_emotion:
                        voice_info += f", 情感: {resolved_emotion}"
                    return await self.send_audio(
                        audio_data=audio_data,
                        audio_format=audio_format,
                        prefix="tts_minimax",
                        voice_info=voice_info,
                    )
                else:
                    error_text = await response.text()
                    logger.error(
                        f"{self.log_prefix} minimax API请求失败[{response.status}]: {error_text[:200]}"
                    )
                    return TTSResult(
                        False,
                        f"minimax API调用失败: {response.status} - {error_text[:100]}",
                        backend_name=self.backend_name,
                    )

        except asyncio.TimeoutError:
            logger.error(f"{self.log_prefix} minimax API请求超时 (配置超时: {timeout}秒)")
            return TTSResult(False, "minimax语音API调用超时", backend_name=self.backend_name)
        except Exception as e:
            logger.error(f"{self.log_prefix} minimax语音执行异常: {e}")
            return TTSResult(False, f"minimax语音执行错误: {e}", backend_name=self.backend_name)
