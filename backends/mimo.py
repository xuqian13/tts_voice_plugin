"""
小米MiMo TTS后端实现
使用小米MiMo语音合成 API (mimo-v2-tts) 进行语音合成
支持预置音色和风格控制（情绪、方言、角色扮演等）
"""

import asyncio
import base64
import json
from typing import Optional, Tuple
from .base import TTSBackendBase, TTSResult
from ..utils.file import TTSFileManager
from ..utils.session import TTSSessionManager
from ..config_keys import ConfigKeys
import logging

logger = logging.getLogger("plugin.tts_voice_plugin.mimo")


class MimoBackend(TTSBackendBase):
    """
    小米MiMo TTS后端

    使用小米MiMo语音合成 API，兼容 OpenAI chat/completions 接口格式
    支持预置音色、风格标签控制和音频标签细粒度控制
    """

    backend_name = "mimo"
    backend_description = "小米MiMo语音合成API"
    support_private_chat = True
    default_audio_format = "wav"

    def get_default_voice(self) -> str:
        """获取默认音色"""
        return self.get_config(ConfigKeys.MIMO_DEFAULT_VOICE, "mimo_default")

    def validate_config(self) -> Tuple[bool, str]:
        """验证配置"""
        api_key = self.get_config(ConfigKeys.MIMO_API_KEY, "")
        if not api_key:
            return False, "小米MiMo TTS后端缺少 api_key 配置"
        return True, ""

    def _build_style_prefix(self, emotion: Optional[str]) -> str:
        """
        构建风格标签前缀

        小米TTS通过在文本开头添加 <style>风格</style> 来控制语音风格
        支持：语速(变快/变慢)、情绪(开心/悲伤/生气)、角色扮演、方言等

        Args:
            emotion: 风格/情感关键词

        Returns:
            风格标签字符串，如 "<style>开心</style>" 或空字符串
        """
        if not emotion:
            return ""
        return f"<style>{emotion}</style>"

    async def execute(
        self,
        text: str,
        voice: Optional[str] = None,
        emotion: Optional[str] = None,
        **kwargs
    ) -> TTSResult:
        """
        执行小米MiMo语音合成

        API格式为 OpenAI chat/completions 兼容接口：
        - 目标文本放在 role=assistant 的 message 中
        - user message 为可选，可辅助调整语气
        - 响应中的音频数据为 base64 编码

        Args:
            text: 待转换的文本
            voice: 音色名称 (mimo_default/default_zh/default_en)
            emotion: 风格/情感参数（开心/悲伤/东北话/唱歌等）

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
        api_url = self.get_config(ConfigKeys.MIMO_API_URL, "https://api.xiaomimimo.com/v1/chat/completions")
        api_key = self.get_config(ConfigKeys.MIMO_API_KEY, "")
        model = self.get_config(ConfigKeys.MIMO_MODEL, "mimo-v2-tts")
        audio_format = self.get_config(ConfigKeys.MIMO_AUDIO_FORMAT, "wav")
        timeout = self.get_config(ConfigKeys.MIMO_TIMEOUT, 60)

        if not voice:
            voice = self.get_default_voice()

        # 构建 assistant 消息内容（含风格标签）
        style_prefix = self._build_style_prefix(emotion)
        assistant_content = f"{style_prefix}{text}" if style_prefix else text

        # 构建请求体（OpenAI chat/completions 兼容格式）
        messages = []

        # user message 可选，帮助调整语气风格
        user_context = self.get_config(ConfigKeys.MIMO_USER_CONTEXT, "")
        if user_context:
            messages.append({"role": "user", "content": user_context})

        # assistant message 包含要合成的目标文本
        messages.append({"role": "assistant", "content": assistant_content})

        request_data = {
            "model": model,
            "messages": messages,
            "audio": {
                "format": audio_format,
                "voice": voice
            }
        }

        headers = {
            "api-key": api_key,
            "Content-Type": "application/json"
        }

        logger.info(
            f"{self.log_prefix} MiMo TTS请求: text='{text[:50]}...' (共{len(text)}字符), "
            f"voice={voice}, emotion={emotion or '无'}"
        )

        try:
            session_manager = await TTSSessionManager.get_instance()
            async with session_manager.post(
                api_url,
                json=request_data,
                headers=headers,
                backend_name="mimo",
                timeout=timeout
            ) as response:
                logger.info(f"{self.log_prefix} MiMo API响应状态码: {response.status}")

                if response.status == 200:
                    response_data = await response.json()

                    # 解析响应：choices[0].message.audio.data (base64编码)
                    try:
                        audio_b64 = response_data["choices"][0]["message"]["audio"]["data"]
                    except (KeyError, IndexError, TypeError) as e:
                        logger.error(f"{self.log_prefix} MiMo响应格式异常: {e}, 响应: {json.dumps(response_data, ensure_ascii=False)[:300]}")
                        return TTSResult(
                            False,
                            f"MiMo响应格式异常: {e}",
                            backend_name=self.backend_name
                        )

                    # base64 解码为音频二进制
                    try:
                        audio_data = base64.b64decode(audio_b64)
                    except Exception as e:
                        logger.error(f"{self.log_prefix} MiMo音频base64解码失败: {e}")
                        return TTSResult(
                            False,
                            f"音频数据解码失败: {e}",
                            backend_name=self.backend_name
                        )

                    # 验证音频数据
                    is_valid, error_msg = TTSFileManager.validate_audio_data(audio_data)
                    if not is_valid:
                        logger.warning(f"{self.log_prefix} MiMo音频数据验证失败: {error_msg}")
                        return TTSResult(False, f"MiMo语音{error_msg}", backend_name=self.backend_name)

                    logger.debug(f"{self.log_prefix} MiMo音频数据验证通过 (大小: {len(audio_data)}字节)")

                    # 使用统一的发送方法
                    return await self.send_audio(
                        audio_data=audio_data,
                        audio_format=audio_format,
                        prefix="tts_mimo",
                        voice_info=f"音色: {voice}" + (f", 风格: {emotion}" if emotion else "")
                    )
                else:
                    error_text = await response.text()
                    logger.error(f"{self.log_prefix} MiMo API请求失败[{response.status}]: {error_text[:200]}")
                    return TTSResult(
                        False,
                        f"MiMo语音API调用失败: {response.status} - {error_text[:100]}",
                        backend_name=self.backend_name
                    )

        except asyncio.TimeoutError:
            logger.error(f"{self.log_prefix} MiMo API请求超时 (配置超时: {timeout}秒)")
            return TTSResult(False, "MiMo语音API调用超时", backend_name=self.backend_name)
        except Exception as e:
            logger.error(f"{self.log_prefix} MiMo语音执行异常: {e}")
            return TTSResult(False, f"MiMo语音执行错误: {e}", backend_name=self.backend_name)
