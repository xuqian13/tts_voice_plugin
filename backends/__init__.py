"""
TTS后端模块
"""

from .base import TTSBackendBase, TTSBackendRegistry, TTSResult
from .ai_voice import AIVoiceBackend
from .gsv2p import GSV2PBackend
from .gpt_sovits import GPTSoVITSBackend
from .doubao import DoubaoBackend
from .cosyvoice import CosyVoiceBackend

# 注册后端
TTSBackendRegistry.register("ai_voice", AIVoiceBackend)
TTSBackendRegistry.register("gsv2p", GSV2PBackend)
TTSBackendRegistry.register("gpt_sovits", GPTSoVITSBackend)
TTSBackendRegistry.register("doubao", DoubaoBackend)
TTSBackendRegistry.register("cosyvoice", CosyVoiceBackend)

__all__ = [
    "TTSBackendBase",
    "TTSBackendRegistry",
    "TTSResult",
    "AIVoiceBackend",
    "GSV2PBackend",
    "GPTSoVITSBackend",
    "DoubaoBackend",
    "CosyVoiceBackend",
]
