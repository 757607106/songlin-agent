"""Redis client manager for task queue persistence."""

import os

import redis.asyncio as aioredis
from src.utils.logging_config import logger


class RedisManager:
    """Redis connection manager with lazy initialization."""

    def __init__(self):
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._client: aioredis.Redis | None = None
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize Redis connection. Returns True if successful."""
        if self._initialized:
            return True

        try:
            self._client = aioredis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            # Test connection
            await self._client.ping()
            self._initialized = True
            logger.info("Redis connection established: {}", self.redis_url)
            return True
        except Exception as e:
            logger.warning("Failed to connect to Redis ({}): {}", self.redis_url, e)
            self._client = None
            self._initialized = False
            return False

    async def get_client(self) -> aioredis.Redis | None:
        """Get Redis client. Returns None if not initialized."""
        if not self._initialized:
            await self.initialize()
        return self._client

    def is_available(self) -> bool:
        """Check if Redis is available."""
        return self._initialized and self._client is not None

    async def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            try:
                await self._client.aclose()
                logger.info("Redis connection closed")
            except Exception as e:
                logger.warning("Error closing Redis connection: {}", e)
            finally:
                self._client = None
                self._initialized = False


redis_manager = RedisManager()

__all__ = ["redis_manager", "RedisManager"]
