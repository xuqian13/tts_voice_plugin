"""
HTTP Session 管理器
提供连接池复用，避免每次请求创建新连接
"""

import asyncio
import aiohttp
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager
from src.common.logger import get_logger

logger = get_logger("tts_session_manager")


class TTSSessionManager:
    """
    TTS HTTP Session 管理器

    提供:
    - 连接池复用
    - 自动超时管理
    - 优雅关闭
    """

    _instance: Optional["TTSSessionManager"] = None
    _lock = asyncio.Lock()

    def __init__(self):
        self._sessions: Dict[str, aiohttp.ClientSession] = {}
        self._default_timeout = 60

    @classmethod
    async def get_instance(cls) -> "TTSSessionManager":
        """获取单例实例"""
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    async def get_session(
        self,
        backend_name: str = "default",
        timeout: int = None
    ) -> aiohttp.ClientSession:
        """
        获取或创建 HTTP Session

        Args:
            backend_name: 后端名称，用于区分不同的session
            timeout: 超时时间（秒）

        Returns:
            aiohttp.ClientSession 实例
        """
        if backend_name not in self._sessions or self._sessions[backend_name].closed:
            timeout_val = timeout or self._default_timeout
            connector = aiohttp.TCPConnector(
                limit=10,  # 每个主机最大连接数
                limit_per_host=5,
                ttl_dns_cache=300,  # DNS缓存5分钟
                force_close=True,  # 禁用连接复用，修复GSV2P等API的兼容性问题
            )
            self._sessions[backend_name] = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=timeout_val)
            )
            logger.debug(f"创建新的HTTP Session: {backend_name}")

        return self._sessions[backend_name]

    async def close_session(self, backend_name: str = None):
        """
        关闭指定或所有 Session

        Args:
            backend_name: 后端名称，为None时关闭所有
        """
        if backend_name:
            if backend_name in self._sessions:
                await self._sessions[backend_name].close()
                del self._sessions[backend_name]
                logger.debug(f"关闭HTTP Session: {backend_name}")
        else:
            for name, session in self._sessions.items():
                if not session.closed:
                    await session.close()
                    logger.debug(f"关闭HTTP Session: {name}")
            self._sessions.clear()

    @asynccontextmanager
    async def post(
        self,
        url: str,
        json: Dict[str, Any] = None,
        headers: Dict[str, str] = None,
        data: Any = None,
        backend_name: str = "default",
        timeout: int = None
    ):
        """
        发送POST请求（异步上下文管理器）

        Args:
            url: 请求URL
            json: JSON请求体
            headers: 请求头
            data: 表单数据
            backend_name: 后端名称
            timeout: 超时时间

        Yields:
            aiohttp.ClientResponse

        Usage:
            async with session_manager.post(url, json=data) as response:
                ...
        """
        session = await self.get_session(backend_name, timeout)

        # 如果指定了不同的超时时间，创建新的超时对象
        req_timeout = None
        if timeout:
            req_timeout = aiohttp.ClientTimeout(total=timeout)

        response = await session.post(
            url,
            json=json,
            headers=headers,
            data=data,
            timeout=req_timeout
        )
        try:
            yield response
        finally:
            response.release()

    @asynccontextmanager
    async def get(
        self,
        url: str,
        headers: Dict[str, str] = None,
        params: Dict[str, Any] = None,
        backend_name: str = "default",
        timeout: int = None
    ):
        """
        发送GET请求（异步上下文管理器）

        Args:
            url: 请求URL
            headers: 请求头
            params: URL参数
            backend_name: 后端名称
            timeout: 超时时间

        Yields:
            aiohttp.ClientResponse

        Usage:
            async with session_manager.get(url) as response:
                ...
        """
        session = await self.get_session(backend_name, timeout)

        # 如果指定了不同的超时时间，创建新的超时对象
        req_timeout = None
        if timeout:
            req_timeout = aiohttp.ClientTimeout(total=timeout)

        response = await session.get(
            url,
            headers=headers,
            params=params,
            timeout=req_timeout
        )
        try:
            yield response
        finally:
            response.release()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close_session()
