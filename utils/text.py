"""
文本处理工具类
"""

import re
from typing import Optional, List


class TTSTextUtils:
    """TTS文本处理工具类"""

    # 网络用语替换映射
    NETWORK_SLANG_MAP = {
        'www': '哈哈哈',
        'hhh': '哈哈',
        '233': '哈哈',
        '666': '厉害',
        '88': '拜拜',
        '...': '。',
        '……': '。'
    }

    # 需要移除的特殊字符正则
    SPECIAL_CHAR_PATTERN = re.compile(
        r'[^\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ffa-zA-Z0-9\s，。！？、；：（）【】"\'.,!?;:()\[\]`-]'
    )

    # 语言检测正则
    CHINESE_PATTERN = re.compile(r'[\u4e00-\u9fff]')
    ENGLISH_PATTERN = re.compile(r'[a-zA-Z]')
    JAPANESE_PATTERN = re.compile(r'[\u3040-\u309f\u30a0-\u30ff]')

    @classmethod
    def clean_text(cls, text: str, max_length: int = 500) -> str:
        """
        清理文本，移除特殊字符，替换网络用语

        Args:
            text: 原始文本
            max_length: 最大长度限制（此参数已不用于硬截断，仅用于参考）

        Returns:
            清理后的文本（不会硬截断，保留完整内容以便上层决策）
        """
        if not text:
            return ""

        # 注释掉文本清理功能，保留原始格式
        # 移除不支持的特殊字符
        # text = cls.SPECIAL_CHAR_PATTERN.sub('', text)

        # 替换常见网络用语
        # for old, new in cls.NETWORK_SLANG_MAP.items():
        #     text = text.replace(old, new)

        return text.strip()

    @classmethod
    def detect_language(cls, text: str) -> str:
        """
        检测文本语言

        Args:
            text: 待检测文本

        Returns:
            语言代码 (zh/ja/en)
        """
        if not text:
            return "zh"

        chinese_chars = len(cls.CHINESE_PATTERN.findall(text))
        english_chars = len(cls.ENGLISH_PATTERN.findall(text))
        japanese_chars = len(cls.JAPANESE_PATTERN.findall(text))
        total_chars = chinese_chars + english_chars + japanese_chars

        if total_chars == 0:
            return "zh"

        chinese_ratio = chinese_chars / total_chars
        japanese_ratio = japanese_chars / total_chars
        english_ratio = english_chars / total_chars

        if chinese_ratio > 0.3:
            return "zh"
        elif japanese_ratio > 0.3:
            return "ja"
        elif english_ratio > 0.8:
            return "en"
        else:
            return "zh"

    @classmethod
    def resolve_voice_alias(
        cls,
        voice: Optional[str],
        alias_map: dict,
        default: str,
        prefix: str = ""
    ) -> str:
        """
        解析音色别名

        Args:
            voice: 用户指定的音色
            alias_map: 别名映射表
            default: 默认音色
            prefix: 内部音色ID前缀（如 "lucy-voice-"）

        Returns:
            解析后的音色ID
        """
        if not voice:
            voice = default

        # 如果已经是内部ID格式，直接返回
        if prefix and voice.startswith(prefix):
            return voice

        # 尝试从别名映射查找
        if voice in alias_map:
            return alias_map[voice]

        # 尝试使用默认值的别名
        if default in alias_map:
            return alias_map[default]

        return default

    @classmethod
    def split_sentences(cls, text: str, min_length: int = 2) -> List[str]:
        """
        将文本分割成句子

        Args:
            text: 待分割文本
            min_length: 最小句子长度，过短的句子会合并到前一句

        Returns:
            句子列表
        """
        if not text:
            return []

        # 使用中英文标点分割
        # 保留分隔符以便后续处理
        pattern = r'([。！？!?；;])'
        parts = re.split(pattern, text)

        sentences = []
        current = ""

        for i, part in enumerate(parts):
            if not part:
                continue

            # 如果是标点符号，附加到当前句子
            if re.match(pattern, part):
                current += part
            else:
                # 如果当前句子不为空，先保存
                if current.strip():
                    sentences.append(current.strip())
                current = part

        # 处理最后一段
        if current.strip():
            sentences.append(current.strip())

        # 合并过短的句子
        if min_length > 0 and len(sentences) > 1:
            merged = []
            for sent in sentences:
                if merged and len(sent) < min_length:
                    # 合并到前一句
                    merged[-1] += sent
                else:
                    merged.append(sent)
            sentences = merged

        return sentences
