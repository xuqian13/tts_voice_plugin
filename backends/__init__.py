"""
TTS后端模块
"""

import sys
sys.dont_write_bytecode = True

from .base import TTSBackendBase, TTSBackendRegistry, TTSResult
from .ai_voice import AIVoiceBackend
from .gsv2p import GSV2PBackend
from .gpt_sovits import GPTSoVITSBackend
from .doubao import DoubaoBackend
from .cosyvoice import CosyVoiceBackend
from .mimo import MimoBackend
from .minimax import MiniMaxBackend

# 注册后端
TTSBackendRegistry.register("ai_voice", AIVoiceBackend)
TTSBackendRegistry.register("gsv2p", GSV2PBackend)
TTSBackendRegistry.register("gpt_sovits", GPTSoVITSBackend)
TTSBackendRegistry.register("doubao", DoubaoBackend)
TTSBackendRegistry.register("cosyvoice", CosyVoiceBackend)
TTSBackendRegistry.register("mimo", MimoBackend)
TTSBackendRegistry.register("minimax", MiniMaxBackend)

__all__ = [
    "TTSBackendBase",
    "TTSBackendRegistry",
    "TTSResult",
    "AIVoiceBackend",
    "GSV2PBackend",
    "GPTSoVITSBackend",
    "DoubaoBackend",
    "CosyVoiceBackend",
    "MimoBackend",
    "MiniMaxBackend",
]
