"""
豆包语音流式响应解析器
基于官方示例实现，确保兼容性和正确性

官方API说明：
- code=0: 继续处理，可能包含 "data"（音频）或 "sentence"（文本）
- code=20000000: 结束标志，可能包含 "usage"（用量统计）
- code>0: 错误响应
"""

import json
import base64
from typing import Tuple, Optional, List
from src.common.logger import get_logger

logger = get_logger("doubao_stream_parser")


class DoubaoStreamParser:
    """
    豆包语音流式响应解析器

    基于官方API实现，忠实还原官方示例逻辑。
    处理流程：
    1. 逐行读取 JSON 响应
    2. 检查状态码：code=0(继续), code=20000000(结束), code>0(错误)
    3. 提取音频数据（code=0 且有 "data" 字段）
    4. 记录日志（code=0 且有 "sentence" 字段）
    """

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
        self._finished: bool = False  # 是否收到结束信号
        self._usage_info: Optional[dict] = None

    def _decode_audio_from_base64(self, audio_base64: str) -> Optional[bytes]:
        """
        从 Base64 字符串解码音频数据

        官方示例中直接使用 base64.b64decode(data["data"])，
        但我们添加了额外的容错和验证。

        Args:
            audio_base64: Base64 编码的音频数据

        Returns:
            解码后的音频字节数据或 None
        """
        if not audio_base64:
            return None

        try:
            # 官方示例直接调用 base64.b64decode()
            # 这里添加容错处理：补充填充符（如果需要）
            padding_needed = len(audio_base64) % 4
            if padding_needed:
                audio_base64 += '=' * (4 - padding_needed)
                logger.debug(
                    f"{self.log_prefix} Base64填充已应用 "
                    f"(原长: {len(audio_base64) - (4 - padding_needed)}, 新长: {len(audio_base64)})"
                )

            audio_bytes = base64.b64decode(audio_base64)

            if not audio_bytes:
                logger.warning(f"{self.log_prefix} Base64解码结果为空")
                return None

            logger.debug(
                f"{self.log_prefix} 音频块解码成功 - 大小: {len(audio_bytes)}字节"
            )
            return audio_bytes

        except Exception as e:
            logger.error(
                f"{self.log_prefix} Base64解码失败: {e} "
                f"(Base64长度: {len(audio_base64)})"
            )
            return None

    def _process_json_line(self, line_str: str) -> Optional[str]:
        """
        处理单行 JSON 数据

        严格按照官方示例逻辑：
        1. 检查 code 字段
        2. code=0 且有 data → 提取音频
        3. code=0 且有 sentence → 记录文本（可选）
        4. code=20000000 → 收到结束信号
        5. code>0 → 错误

        Args:
            line_str: JSON 字符串

        Returns:
            如果收到结束信号，返回 "END"；如果发生错误，返回错误信息；否则返回 None
        """
        try:
            json_obj = json.loads(line_str)
        except json.JSONDecodeError as e:
            logger.debug(f"{self.log_prefix} JSON解析失败: {e}")
            return None
        except Exception as e:
            logger.warning(f"{self.log_prefix} JSON处理异常: {e}")
            return None

        if not isinstance(json_obj, dict):
            logger.debug(
                f"{self.log_prefix} 收到非字典JSON对象: {type(json_obj).__name__}"
            )
            return None

        code = json_obj.get("code", -1)

        # ✅ 官方逻辑：处理 code=0 的数据帧
        if code == 0:
            # 检查是否有音频数据
            if "data" in json_obj and json_obj["data"]:
                chunk_audio = self._decode_audio_from_base64(json_obj["data"])
                if chunk_audio:
                    self._audio_chunks.append(chunk_audio)
                    logger.debug(
                        f"{self.log_prefix} 音频块#{len(self._audio_chunks)} 已接收 "
                        f"(大小: {len(chunk_audio)}字节)"
                    )

            # 检查是否有文本/句子信息（可选）
            if "sentence" in json_obj and json_obj["sentence"]:
                sentence_data = json_obj.get("sentence", {})
                logger.debug(
                    f"{self.log_prefix} 收到句子数据: {sentence_data}"
                )

            return None  # 继续处理

        # ✅ 官方逻辑：处理 code=20000000 的结束帧
        elif code == 20000000:
            logger.info(f"{self.log_prefix} 收到流结束信号 (code=20000000)")

            # 记录用量信息（如果有）
            if "usage" in json_obj:
                self._usage_info = json_obj["usage"]
                logger.info(
                    f"{self.log_prefix} 豆包用量信息: {self._usage_info}"
                )

            self._finished = True
            return "END"  # 表示流已结束

        # ✅ 官方逻辑：错误处理
        elif code and code > 0:
            error_msg = json_obj.get("message", f"未知错误 (code={code})")
            logger.error(
                f"{self.log_prefix} 豆包语音API返回错误 "
                f"(code={code}): {error_msg}"
            )
            self._error_message = error_msg
            return error_msg  # 返回错误信息

        # 未知状态码
        else:
            logger.debug(
                f"{self.log_prefix} 收到未知状态码: code={code}"
            )
            return None

    def _find_data_chunk_offset(self, header: bytes) -> int:
        """
        在 WAV header 中查找 'data' 块的位置

        豆包返回的 WAV 可能包含额外的元数据块（如 LIST/INFO），
        导致 'data' 块不在标准的 44 字节位置。

        Args:
            header: WAV 文件头部数据

        Returns:
            data 块数据开始的位置（即 'data' + 4字节大小之后）
        """
        pos = 12  # 跳过 RIFF(4) + size(4) + WAVE(4)

        while pos < len(header) - 8:
            chunk_id = header[pos:pos+4]
            chunk_size = int.from_bytes(header[pos+4:pos+8], 'little')

            if chunk_id == b'data':
                return pos + 8  # 返回音频数据开始位置

            # 移动到下一个块
            pos += 8 + chunk_size
            # WAV 块需要对齐到偶数字节
            if chunk_size % 2 == 1:
                pos += 1

        # 未找到 data 块，返回默认值
        return 44

    def _merge_audio_chunks(self, chunks: List[bytes]) -> bytes:
        """
        合并音频块，处理 WAV 格式的流式响应

        豆包流式 WAV 响应特点：
        1. 第一个块包含完整 header（可能 > 44 字节，含 LIST/INFO 元数据）
        2. header 中的大小字段是 0xFFFFFFFF（流式占位符）
        3. 后续块是纯音频数据（无 header）
        4. 需要在合并后修正大小字段

        Args:
            chunks: 音频数据块列表

        Returns:
            合并后的有效 WAV 文件
        """
        if not chunks:
            return b''

        first_chunk = chunks[0]

        # 检查是否是 WAV 格式（RIFF header）
        if len(first_chunk) < 44 or first_chunk[:4] != b'RIFF':
            # 不是 WAV 格式（如 MP3），直接拼接
            return b''.join(chunks)

        # 查找 data 块的实际位置
        data_offset = self._find_data_chunk_offset(first_chunk)
        logger.debug(f"{self.log_prefix} WAV data 块偏移: {data_offset} 字节")

        # 提取 header 和第一块的音频数据
        header = bytearray(first_chunk[:data_offset])
        data_parts = [first_chunk[data_offset:]]
        skipped_headers = 0

        # 处理后续块
        for chunk in chunks[1:]:
            if len(chunk) > 44 and chunk[:4] == b'RIFF':
                # 后续块也有 RIFF header，需要跳过
                chunk_data_offset = self._find_data_chunk_offset(chunk)
                data_parts.append(chunk[chunk_data_offset:])
                skipped_headers += 1
            else:
                # 纯音频数据
                data_parts.append(chunk)

        # 合并所有音频数据
        audio_data = b''.join(data_parts)
        audio_size = len(audio_data)

        # 修正 WAV header 中的大小字段
        # 字节 4-7: 文件总大小 - 8 = (header_size - 8) + audio_size
        file_size = len(header) - 8 + audio_size
        header[4:8] = file_size.to_bytes(4, 'little')

        # 修正 data 块的大小字段（位于 data_offset - 4 处）
        header[data_offset-4:data_offset] = audio_size.to_bytes(4, 'little')

        if skipped_headers > 0 or audio_size > 0:
            logger.info(
                f"{self.log_prefix} WAV 流式合并完成: "
                f"header={len(header)}字节, 音频={audio_size}字节, "
                f"跳过重复header={skipped_headers}"
            )

        return bytes(header) + audio_data

    def feed_chunk(self, chunk: bytes) -> Optional[str]:
        """
        输入一块数据

        Args:
            chunk: 网络数据块

        Returns:
            如果遇到错误或结束，返回相应信息；否则返回 None
        """
        if not chunk:
            return None

        self._buffer += chunk
        self._total_bytes += len(chunk)

        # 按行处理（官方示例使用 iter_lines）
        while b'\n' in self._buffer:
            line_bytes, self._buffer = self._buffer.split(b'\n', 1)

            # 尝试解码行数据
            try:
                line_str = line_bytes.decode('utf-8', errors='replace').strip()
            except Exception as e:
                logger.warning(
                    f"{self.log_prefix} 行解码失败: {e}, 跳过该行"
                )
                self._line_count += 1
                continue

            if not line_str:
                continue

            self._line_count += 1

            # 处理该行
            result = self._process_json_line(line_str)

            # 如果收到结束信号或错误，立即返回
            if result == "END":
                return None  # 正常结束
            elif result:  # 返回的是错误信息
                return result

        return None

    def finalize(self) -> Tuple[Optional[bytes], Optional[str]]:
        """
        完成解析，处理剩余数据

        Returns:
            (audio_data, error_message)
            - audio_data: 合并后的音频数据（成功时）
            - error_message: 错误信息（失败时）
        """
        # 处理剩余的 buffer 中的最后一行
        if self._buffer.strip():
            try:
                line_str = self._buffer.decode('utf-8', errors='replace').strip()
                if line_str:
                    logger.debug(
                        f"{self.log_prefix} 处理最后的buffer数据 "
                        f"(长度: {len(line_str)}字符)"
                    )
                    result = self._process_json_line(line_str)
                    if result and result != "END":
                        # 最后的 buffer 包含错误
                        self._error_message = result
            except Exception as e:
                logger.warning(
                    f"{self.log_prefix} 最后buffer解析异常: {e}"
                )

        logger.info(
            f"{self.log_prefix} 豆包流解析完成 - "
            f"处理行数: {self._line_count}, "
            f"音频块数: {len(self._audio_chunks)}, "
            f"接收字节数: {self._total_bytes}, "
            f"正常结束: {self._finished}"
        )

        # 检查是否有错误
        if self._error_message:
            logger.error(
                f"{self.log_prefix} 豆包API返回错误: {self._error_message}"
            )
            return None, f"豆包语音API错误: {self._error_message}"

        # 检查是否有音频数据
        if not self._audio_chunks:
            if self._total_bytes == 0:
                logger.warning(
                    f"{self.log_prefix} 豆包API未返回任何数据"
                )
                return None, "未收到任何响应数据"

            logger.warning(
                f"{self.log_prefix} 收到 {self._total_bytes} 字节数据但无音频块"
            )
            return None, "豆包语音未返回任何音频数据"

        # ✅ 额外的数据完整性检查
        # 过滤掉过小的块（可能是损坏或无效的）
        min_chunk_size = 50  # 最小块大小
        valid_chunks = [
            chunk for chunk in self._audio_chunks
            if len(chunk) >= min_chunk_size
        ]

        if not valid_chunks:
            logger.error(
                f"{self.log_prefix} 所有音频块都太小 (可能是损坏的数据)"
            )
            logger.debug(
                f"{self.log_prefix} 块大小分布: {[len(c) for c in self._audio_chunks]}"
            )
            return None, "音频数据不完整或已损坏"

        # 合并所有有效的音频数据（处理 WAV 多 header 问题）
        merged_audio = self._merge_audio_chunks(valid_chunks)

        logger.info(
            f"{self.log_prefix} 音频合并完成 - "
            f"有效块数: {len(valid_chunks)}/{len(self._audio_chunks)}, "
            f"总大小: {len(merged_audio)}字节"
        )

        return merged_audio, None

    @classmethod
    async def parse_response(
        cls,
        response,
        log_prefix: str = "[DoubaoParser]"
    ) -> Tuple[Optional[bytes], Optional[str]]:
        """
        解析豆包 API 的流式响应

        Args:
            response: aiohttp 响应对象
            log_prefix: 日志前缀

        Returns:
            (audio_data, error_message)
        """
        parser = cls(log_prefix)

        # 逐块读取响应流
        async for chunk in response.content.iter_any():
            result = parser.feed_chunk(chunk)

            # 如果遇到错误，立即返回
            if result and result != "END":
                return None, result

        # 完成解析，处理剩余数据
        return parser.finalize()
