"""
豆包语音流式响应解析器
提取为独立类，简化 DoubaoBackend 的逻辑
"""

import json
import base64
from typing import Tuple, Optional, List
from src.common.logger import get_logger

logger = get_logger("doubao_stream_parser")


class DoubaoStreamParser:
    """
    豆包语音流式响应解析器

    负责解析豆包 API 返回的流式 JSON 响应
    """

    # 豆包API成功响应码
    SUCCESS_CODES = [0, 20000000]

    def __init__(self, log_prefix: str = "[DoubaoParser]"):
        """
        初始化解析器

        Args:
            log_prefix: 日志前缀
        """
        self.log_prefix = log_prefix
        self._audio_chunks: List[bytes] = []
        self._buffer: bytes = b''
        self._line_count: int = 0
        self._total_bytes: int = 0
        self._error_message: Optional[str] = None

    def _decode_audio_from_data(self, data_obj: any) -> Optional[bytes]:
        """
        从数据对象中解码音频

        Args:
            data_obj: 数据对象（可能是字符串或字典）

        Returns:
            解码后的音频数据或 None
        """
        try:
            # 如果是字符串，直接解码
            if isinstance(data_obj, str) and data_obj:
                return base64.b64decode(data_obj)

            # 如果是字典，提取 audio 字段
            if isinstance(data_obj, dict):
                audio_base64 = data_obj.get("audio", "")
                if audio_base64:
                    return base64.b64decode(audio_base64)

        except Exception as e:
            logger.debug(f"{self.log_prefix} base64解码失败: {e}")

        return None

    def _process_json_line(self, line_str: str) -> bool:
        """
        处理单行 JSON 数据

        Args:
            line_str: JSON 字符串

        Returns:
            是否遇到错误（True 表示有错误）
        """
        try:
            json_obj = json.loads(line_str)

            if not isinstance(json_obj, dict):
                return False

            # 检查错误码
            code = json_obj.get("code")
            if code is not None and code not in self.SUCCESS_CODES:
                self._error_message = json_obj.get("message", "未知错误")
                logger.error(f"{self.log_prefix} 豆包语音API返回错误码 {code}: {self._error_message}")
                return True  # 表示有错误

            # 提取音频数据
            data_obj = json_obj.get("data")
            audio_data = self._decode_audio_from_data(data_obj)
            if audio_data:
                self._audio_chunks.append(audio_data)

            return False  # 无错误

        except json.JSONDecodeError:
            return False  # JSON 解析失败，跳过该行
        except Exception as e:
            logger.debug(f"{self.log_prefix} 处理响应行时出错: {e}")
            return False

    def feed_chunk(self, chunk: bytes) -> Optional[str]:
        """
        输入一块数据

        Args:
            chunk: 数据块

        Returns:
            错误信息（如果有），否则返回 None
        """
        self._buffer += chunk
        self._total_bytes += len(chunk)

        # 处理完整的行
        while b'\n' in self._buffer:
            line_bytes, self._buffer = self._buffer.split(b'\n', 1)
            line_str = line_bytes.decode('utf-8').strip()

            if not line_str:
                continue

            self._line_count += 1

            # 处理该行，如果遇到错误则返回
            if self._process_json_line(line_str):
                return self._error_message

        return None

    def finalize(self) -> Tuple[Optional[bytes], Optional[str]]:
        """
        完成解析，处理剩余数据

        Returns:
            (audio_data, error_message)
            - audio_data: 合并后的音频数据（成功时）
            - error_message: 错误信息（失败时）
        """
        # 处理剩余的buffer
        if self._buffer.strip():
            try:
                line_str = self._buffer.decode('utf-8').strip()
                self._process_json_line(line_str)
            except Exception:
                pass  # 忽略最后buffer的解析错误

        logger.info(
            f"{self.log_prefix} 处理完成: {self._line_count}行, "
            f"音频块: {len(self._audio_chunks)}, 总字节数: {self._total_bytes}"
        )

        # 检查是否有错误
        if self._error_message:
            return None, f"豆包语音API错误: {self._error_message}"

        # 检查是否有音频数据
        if not self._audio_chunks:
            if self._total_bytes == 0:
                return None, "未收到任何响应数据"
            return None, "豆包语音未返回任何音频数据"

        # 合并音频数据
        return b''.join(self._audio_chunks), None

    @classmethod
    async def parse_response(cls, response, log_prefix: str = "[DoubaoParser]") -> Tuple[Optional[bytes], Optional[str]]:
        """
        解析豆包 API 的流式响应（静态方法，简化调用）

        Args:
            response: aiohttp 响应对象
            log_prefix: 日志前缀

        Returns:
            (audio_data, error_message)
        """
        parser = cls(log_prefix)

        # 逐块读取响应
        async for chunk in response.content.iter_any():
            error_msg = parser.feed_chunk(chunk)
            if error_msg:
                # 遇到错误，提前返回
                return None, error_msg

        # 完成解析
        return parser.finalize()
