"""
AI Voice 后端实现
使用 MaiCore 内置的 AI 语音功能
"""

from typing import Optional, Callable, Dict
from .base import TTSBackendBase, TTSResult
from ..utils.text import TTSTextUtils
from ..config_keys import ConfigKeys
from src.common.logger import get_logger

logger = get_logger("tts_ai_voice")

# AI Voice 音色映射表
AI_VOICE_ALIAS_MAP = {
    "小新": "lucy-voice-laibixiaoxin",
    "猴哥": "lucy-voice-houge",
    "四郎": "lucy-voice-silang",
    "东北老妹儿": "lucy-voice-guangdong-f1",
    "广西大表哥": "lucy-voice-guangxi-m1",
    "妲己": "lucy-voice-daji",
    "霸道总裁": "lucy-voice-lizeyan",
    "酥心御姐": "lucy-voice-suxinjiejie",
    "说书先生": "lucy-voice-m8",
    "憨憨小弟": "lucy-voice-male1",
    "憨厚老哥": "lucy-voice-male3",
    "吕布": "lucy-voice-lvbu",
    "元气少女": "lucy-voice-xueling",
    "文艺少女": "lucy-voice-f37",
    "磁性大叔": "lucy-voice-male2",
    "邻家小妹": "lucy-voice-female1",
    "低沉男声": "lucy-voice-m14",
    "傲娇少女": "lucy-voice-f38",
    "爹系男友": "lucy-voice-m101",
    "暖心姐姐": "lucy-voice-female2",
    "温柔妹妹": "lucy-voice-f36",
    "书香少女": "lucy-voice-f34"
}


class AIVoiceBackend(TTSBackendBase):
    """
    AI Voice 后端

    使用 MaiCore 内置的 AI 语音功能
    注意：仅支持群聊环境
    """

    backend_name = "ai_voice"
    backend_description = "MaiCore内置AI语音（仅群聊）"
    support_private_chat = False  # 不支持私聊
    default_audio_format = ""  # AI Voice不需要音频格式

    def __init__(self, config_getter, log_prefix: str = ""):
        super().__init__(config_getter, log_prefix)
        self._send_command = None  # 由外部注入

    def set_send_command(self, send_command_func: Callable) -> None:
        """设置发送命令的函数（由Action/Command注入）"""
        self._send_command = send_command_func

    def get_default_voice(self) -> str:
        """获取默认音色"""
        return self.get_config(ConfigKeys.AI_VOICE_DEFAULT_CHARACTER, "温柔妹妹")

    def resolve_voice(self, voice: Optional[str]) -> str:
        """解析音色别名"""
        alias_map: Dict[str, str] = self.get_config(
            ConfigKeys.AI_VOICE_ALIAS_MAP,
            AI_VOICE_ALIAS_MAP
        )
        default_voice = self.get_default_voice()
        return TTSTextUtils.resolve_voice_alias(
            voice,
            alias_map,
            default_voice,
            prefix="lucy-voice-"
        )

    async def execute(
        self,
        text: str,
        voice: Optional[str] = None,
        **kwargs
    ) -> TTSResult:
        """
        执行AI Voice语音合成

        Args:
            text: 待转换的文本
            voice: 音色名称或别名

        Returns:
            TTSResult
        """
        if not self._send_command:
            return TTSResult(
                success=False,
                message="AI Voice后端未正确初始化（缺少send_command）",
                backend_name=self.backend_name
            )

        # 解析音色
        character = self.resolve_voice(voice)

        try:
            success = await self._send_command(
                command_name="AI_VOICE_SEND",
                args={"text": text, "character": character},
                storage_message=False
            )

            if success:
                logger.info(f"{self.log_prefix} AI语音发送成功 (音色: {character})")
                return TTSResult(
                    success=True,
                    message=f"成功发送AI语音 (音色: {character})",
                    backend_name=self.backend_name
                )
            else:
                return TTSResult(
                    success=False,
                    message="AI语音命令发送失败",
                    backend_name=self.backend_name
                )

        except Exception as e:
            logger.error(f"{self.log_prefix} AI语音执行错误: {e}")
            return TTSResult(
                success=False,
                message=f"AI语音执行错误: {e}",
                backend_name=self.backend_name
            )
