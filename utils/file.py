"""
文件操作工具类
提供异步文件操作、临时文件管理等功能
"""

import os
import uuid
import tempfile
import asyncio
import base64
from typing import Optional
from src.common.logger import get_logger

logger = get_logger("tts_file_manager")

# 音频数据最小有效大小（字节）
MIN_AUDIO_SIZE = 100


class TTSFileManager:
    """
    TTS文件管理器

    提供:
    - 临时文件创建（避免并发冲突）
    - 异步文件写入
    - 自动清理
    - 相对路径和绝对路径支持
    """

    # 临时文件目录（兼容旧代码）
    _temp_dir: Optional[str] = None

    # 项目根目录（用于解析相对路径）
    _project_root: Optional[str] = None

    @classmethod
    def set_project_root(cls, root_path: str):
        """设置项目根目录"""
        if os.path.isdir(root_path):
            cls._project_root = root_path
            logger.debug(f"设置项目根目录: {root_path}")
        else:
            logger.warning(f"项目根目录不存在: {root_path}")

    @classmethod
    def get_project_root(cls) -> str:
        """获取项目根目录"""
        if cls._project_root is None:
            # 尝试从当前文件位置推断项目根目录
            current_file = os.path.abspath(__file__)
            # 假设结构是: project_root/plugins/tts_voice_plugin/utils/file.py
            cls._project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_file))))
            logger.debug(f"自动推断项目根目录: {cls._project_root}")
        return cls._project_root

    @classmethod
    def resolve_path(cls, path: str) -> str:
        """
        解析路径（支持相对路径和绝对路径）

        Args:
            path: 路径字符串

        Returns:
            解析后的绝对路径
        """
        if os.path.isabs(path):
            # 已经是绝对路径
            return path
        else:
            # 相对路径，相对于项目根目录
            return os.path.join(cls.get_project_root(), path)

    @classmethod
    def ensure_dir(cls, dir_path: str) -> bool:
        """
        确保目录存在，不存在则创建

        Args:
            dir_path: 目录路径

        Returns:
            是否成功
        """
        try:
            os.makedirs(dir_path, exist_ok=True)
            return True
        except Exception as e:
            logger.error(f"创建目录失败: {dir_path}, 错误: {e}")
            return False

    @classmethod
    def get_temp_dir(cls) -> str:
        """
        获取临时文件目录（已废弃，保留兼容性）

        Returns:
            临时目录路径
        """
        if cls._temp_dir is None:
            cls._temp_dir = tempfile.gettempdir()
        return cls._temp_dir

    @classmethod
    def set_temp_dir(cls, path: str):
        """
        设置临时文件目录（已废弃，保留兼容性）

        Args:
            path: 目录路径
        """
        if os.path.isdir(path):
            cls._temp_dir = path
        else:
            raise ValueError(f"目录不存在: {path}")

    @classmethod
    def generate_temp_path(cls, prefix: str = "tts", suffix: str = ".mp3", output_dir: str = "") -> str:
        """
        生成唯一的临时文件路径

        Args:
            prefix: 文件名前缀
            suffix: 文件扩展名
            output_dir: 输出目录（支持相对路径和绝对路径，留空使用项目根目录）

        Returns:
            临时文件的绝对路径
        """
        # 确定输出目录
        if not output_dir:
            # 默认使用项目根目录
            resolved_dir = cls.get_project_root()
        else:
            # 解析用户配置的路径
            resolved_dir = cls.resolve_path(output_dir)
            # 确保目录存在
            if not cls.ensure_dir(resolved_dir):
                # 如果创建失败，降级到项目根目录
                logger.warning(f"无法创建输出目录 {resolved_dir}，使用项目根目录")
                resolved_dir = cls.get_project_root()

        # 生成唯一文件名
        unique_id = uuid.uuid4().hex[:12]
        filename = f"{prefix}_{unique_id}{suffix}"
        return os.path.join(resolved_dir, filename)

    @classmethod
    async def write_audio_async(cls, path: str, data: bytes) -> bool:
        """
        异步写入音频数据到文件

        Args:
            path: 文件路径
            data: 音频二进制数据

        Returns:
            是否写入成功
        """
        try:
            # 使用线程池执行同步文件写入，避免阻塞事件循环
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, cls._write_file_sync, path, data)
            logger.debug(f"音频文件写入成功: {path} ({len(data)} bytes)")
            return True
        except IOError as e:
            logger.error(f"写入音频文件失败: {path}, 错误: {e}")
            return False
        except Exception as e:
            logger.error(f"写入音频文件时发生未知错误: {path}, 错误: {e}")
            return False

    @staticmethod
    def _write_file_sync(path: str, data: bytes):
        """同步写入文件（内部方法）"""
        with open(path, "wb") as f:
            f.write(data)

    @classmethod
    def write_audio_sync(cls, path: str, data: bytes) -> bool:
        """
        同步写入音频数据到文件

        Args:
            path: 文件路径
            data: 音频二进制数据

        Returns:
            是否写入成功
        """
        try:
            cls._write_file_sync(path, data)
            logger.debug(f"音频文件写入成功: {path} ({len(data)} bytes)")
            return True
        except IOError as e:
            logger.error(f"写入音频文件失败: {path}, 错误: {e}")
            return False
        except Exception as e:
            logger.error(f"写入音频文件时发生未知错误: {path}, 错误: {e}")
            return False

    @classmethod
    def cleanup_file(cls, path: str, silent: bool = True) -> bool:
        """
        清理临时文件

        Args:
            path: 文件路径
            silent: 是否静默处理错误

        Returns:
            是否清理成功
        """
        try:
            if path and os.path.exists(path):
                os.remove(path)
                logger.debug(f"临时文件已清理: {path}")
                return True
            return False
        except Exception as e:
            if not silent:
                logger.warning(f"清理临时文件失败: {path}, 错误: {e}")
            return False

    @classmethod
    async def cleanup_file_async(cls, path: str, delay: float = 0) -> bool:
        """
        异步清理临时文件（可延迟）

        Args:
            path: 文件路径
            delay: 延迟秒数

        Returns:
            是否清理成功
        """
        if delay > 0:
            await asyncio.sleep(delay)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, cls.cleanup_file, path, True)

    @classmethod
    def validate_audio_data(cls, data: bytes, min_size: int = None) -> tuple:
        """
        验证音频数据有效性

        Args:
            data: 音频二进制数据
            min_size: 最小有效大小

        Returns:
            (is_valid, error_message)
        """
        if data is None:
            return False, "音频数据为空"

        min_size = min_size or MIN_AUDIO_SIZE

        if len(data) < min_size:
            return False, f"音频数据过小({len(data)}字节 < {min_size}字节)"

        return True, ""

    @classmethod
    def audio_to_base64(cls, data: bytes) -> str:
        """
        将音频数据转换为base64字符串

        Args:
            data: 音频二进制数据

        Returns:
            base64编码的字符串
        """
        try:
            return base64.b64encode(data).decode('utf-8')
        except Exception as e:
            logger.error(f"音频数据转base64失败: {e}")
            return ""
