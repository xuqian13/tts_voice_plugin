"""
TTS后端抽象基类和注册表
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Type, Optional, Any, Callable, Tuple, Union
from src.common.logger import get_logger
from ..config_keys import ConfigKeys

logger = get_logger("tts_backend")


@dataclass
class TTSResult:
    """TTS执行结果"""
    success: bool
    message: str
    audio_path: Optional[str] = None
    backend_name: str = ""

    def __iter__(self):
        """支持解包为 (success, message)"""
        return iter((self.success, self.message))


class TTSBackendBase(ABC):
    """
    TTS后端抽象基类

    所有TTS后端必须继承此类并实现 execute 方法
    """

    # 后端名称（子类必须覆盖）
    backend_name: str = "base"

    # 后端描述
    backend_description: str = "TTS后端基类"

    # 是否支持私聊
    support_private_chat: bool = True

    # 默认音频格式
    default_audio_format: str = "mp3"

    def __init__(self, config_getter: Callable[[str, Any], Any], log_prefix: str = ""):
        """
        初始化后端

        Args:
            config_getter: 配置获取函数，签名为 get_config(key, default)
            log_prefix: 日志前缀
        """
        self.get_config = config_getter
        self.log_prefix = log_prefix or f"[{self.backend_name}]"
        self._send_custom = None

    def set_send_custom(self, send_custom_func: Callable) -> None:
        """设置发送自定义消息的函数"""
        self._send_custom = send_custom_func

    async def send_audio(
        self,
        audio_data: bytes,
        audio_format: str = "mp3",
        prefix: str = "tts",
        voice_info: str = ""
    ) -> TTSResult:
        """
        统一的音频发送方法

        Args:
            audio_data: 音频二进制数据
            audio_format: 音频格式（如mp3、wav）
            prefix: 文件名前缀
            voice_info: 音色信息（用于日志）

        Returns:
            TTSResult
        """
        from ..utils.file import TTSFileManager

        # 检查是否使用base64发送
        use_base64 = self.get_config(ConfigKeys.GENERAL_USE_BASE64_AUDIO, False)
        logger.debug(f"{self.log_prefix} 开始发送音频 (原始大小: {len(audio_data)}字节, 格式: {audio_format})")

        if use_base64:
            # 使用base64编码发送
            base64_audio = TTSFileManager.audio_to_base64(audio_data)
            if not base64_audio:
                return TTSResult(False, "音频数据转base64失败", backend_name=self.backend_name)

            logger.debug(f"{self.log_prefix} base64编码完成，准备通过send_custom发送")
            if self._send_custom:
                await self._send_custom(message_type="voice", content=base64_audio)
                logger.info(f"{self.log_prefix} 语音已通过send_custom发送 (base64模式, 音频大小: {len(audio_data)}字节)")
            else:
                logger.warning(f"{self.log_prefix} send_custom未设置，无法发送语音")
                return TTSResult(False, "send_custom回调未设置", backend_name=self.backend_name)

            return TTSResult(
                success=True,
                message=f"成功发送{self.backend_name}语音{(' ('+voice_info+')') if voice_info else ''}, base64模式",
                backend_name=self.backend_name
            )
        else:
            # 使用文件路径发送
            output_dir = self.get_config(ConfigKeys.GENERAL_AUDIO_OUTPUT_DIR, "")
            audio_path = TTSFileManager.generate_temp_path(
                prefix=prefix,
                suffix=f".{audio_format}",
                output_dir=output_dir
            )

            if not await TTSFileManager.write_audio_async(audio_path, audio_data):
                return TTSResult(False, "保存音频文件失败", backend_name=self.backend_name)

            logger.debug(f"{self.log_prefix} 音频文件已保存, 路径: {audio_path}")
            # 发送语音
            if self._send_custom:
                await self._send_custom(message_type="voiceurl", content=audio_path)
                logger.info(f"{self.log_prefix} 语音已通过send_custom发送 (文件路径模式, 路径: {audio_path})")
                # 延迟清理临时文件
                asyncio.create_task(TTSFileManager.cleanup_file_async(audio_path, delay=30))
            else:
                logger.warning(f"{self.log_prefix} send_custom未设置，无法发送语音")
                return TTSResult(False, "send_custom回调未设置", backend_name=self.backend_name)

            return TTSResult(
                success=True,
                message=f"成功发送{self.backend_name}语音{(' ('+voice_info+')') if voice_info else ''}",
                audio_path=audio_path,
                backend_name=self.backend_name
            )

    @abstractmethod
    async def execute(
        self,
        text: str,
        voice: Optional[str] = None,
        **kwargs
    ) -> TTSResult:
        """
        执行TTS转换

        Args:
            text: 待转换的文本
            voice: 音色/风格
            **kwargs: 其他参数（如emotion等）

        Returns:
            TTSResult 包含执行结果
        """
        raise NotImplementedError

    def validate_config(self) -> Tuple[bool, str]:
        """
        验证后端配置是否完整

        Returns:
            (is_valid, error_message)
        """
        return True, ""

    def get_default_voice(self) -> str:
        """获取默认音色"""
        return ""

    def is_available(self) -> bool:
        """检查后端是否可用"""
        is_valid, _ = self.validate_config()
        return is_valid


class TTSBackendRegistry:
    """
    TTS后端注册表

    使用策略模式 + 工厂模式管理后端
    """

    _backends: Dict[str, Type[TTSBackendBase]] = {}

    @classmethod
    def register(cls, name: str, backend_class: Type[TTSBackendBase]) -> None:
        """
        注册后端

        Args:
            name: 后端名称
            backend_class: 后端类
        """
        cls._backends[name] = backend_class
        logger.debug(f"注册TTS后端: {name}")

    @classmethod
    def unregister(cls, name: str) -> None:
        """注销后端"""
        if name in cls._backends:
            del cls._backends[name]

    @classmethod
    def get(cls, name: str) -> Optional[Type[TTSBackendBase]]:
        """获取后端类"""
        return cls._backends.get(name)

    @classmethod
    def create(
        cls,
        name: str,
        config_getter: Callable[[str, Any], Any],
        log_prefix: str = ""
    ) -> Optional[TTSBackendBase]:
        """
        创建后端实例

        Args:
            name: 后端名称
            config_getter: 配置获取函数
            log_prefix: 日志前缀

        Returns:
            后端实例或None
        """
        backend_class = cls.get(name)
        if backend_class:
            return backend_class(config_getter, log_prefix)
        return None

    @classmethod
    def list_backends(cls) -> list[str]:
        """列出所有已注册的后端名称"""
        return list(cls._backends.keys())

    @classmethod
    def is_registered(cls, name: str) -> bool:
        """检查后端是否已注册"""
        return name in cls._backends
