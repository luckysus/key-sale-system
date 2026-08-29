import hashlib
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

from redis.asyncio import Redis
from redis.exceptions import RedisError


class RedeemGuardError(RuntimeError):
    pass


class RedeemGuardUnavailable(RedeemGuardError):
    pass


class RedeemRateLimited(RedeemGuardError):
    def __init__(self, retry_after: int):
        super().__init__("请求过于频繁，请稍后再试")
        self.retry_after = int(retry_after)


class RedeemCardBusy(RedeemGuardError):
    pass


class RedeemServerBusy(RedeemGuardError):
    pass


RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


ACQUIRE_SEMAPHORE_SCRIPT = """
local redis_time = redis.call('TIME')
local now = tonumber(redis_time[1]) + tonumber(redis_time[2]) / 1000000
local lease_seconds = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then
  return 0
end
redis.call('ZADD', KEYS[1], now + lease_seconds, ARGV[1])
redis.call('EXPIRE', KEYS[1], lease_seconds)
return 1
"""


def _digest(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _redis_failure(exc: Exception) -> RedeemGuardUnavailable:
    return RedeemGuardUnavailable("兑换安全服务暂时不可用")


def validate_lease_seconds(lease_seconds: int, timeout_seconds: int, safety_margin: int = 30) -> int:
    lease = int(lease_seconds)
    minimum = int(timeout_seconds) + int(safety_margin)
    if lease < minimum:
        raise ValueError(f"REDEEM_LEASE_SECONDS must be at least {minimum}")
    return lease


@dataclass
class RedeemAdmission:
    guard: "RedeemGuard"
    card_key: str
    token: str
    released: bool = False

    async def release(self) -> None:
        if self.released:
            return
        self.released = True
        try:
            await self.guard.redis.zrem(self.guard.semaphore_key, self.token)
            await self.guard.redis.eval(RELEASE_LOCK_SCRIPT, 1, self.card_key, self.token)
        except (RedisError, ConnectionError, OSError, TimeoutError):
            # Both records have short leases and recover without an unsafe delete.
            return


class RedeemGuard:
    def __init__(
        self,
        redis: Any,
        *,
        ip_limit: int = 20,
        ip_window_seconds: int = 60,
        card_limit: int = 5,
        card_window_seconds: int = 300,
        failure_threshold: int = 5,
        failure_window_seconds: int = 600,
        concurrency: int = 10,
        lease_seconds: int = 210,
        key_prefix: str = "ks:redeem",
    ):
        self.redis = redis
        self.ip_limit = max(1, int(ip_limit))
        self.ip_window_seconds = max(1, int(ip_window_seconds))
        self.card_limit = max(1, int(card_limit))
        self.card_window_seconds = max(1, int(card_window_seconds))
        self.failure_threshold = max(1, int(failure_threshold))
        self.failure_window_seconds = max(1, int(failure_window_seconds))
        self.concurrency = max(1, int(concurrency))
        self.lease_seconds = max(1, int(lease_seconds))
        self.key_prefix = key_prefix.strip(":") or "ks:redeem"
        self.semaphore_key = f"{self.key_prefix}:leases"

    @classmethod
    def from_url(cls, url: str, **kwargs) -> "RedeemGuard":
        client = Redis.from_url(
            url,
            decode_responses=False,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
        return cls(client, **kwargs)

    def _key(self, scope: str, value: str) -> str:
        return f"{self.key_prefix}:{scope}:{_digest(value)}"

    async def ensure_available(self) -> None:
        try:
            await self.redis.ping()
        except (RedisError, ConnectionError, OSError, TimeoutError) as exc:
            raise _redis_failure(exc) from exc

    async def _increment(self, key: str, ttl_seconds: int) -> int:
        try:
            pipe = self.redis.pipeline(transaction=True)
            pipe.incr(key)
            pipe.expire(key, int(ttl_seconds), nx=True)
            values = await pipe.execute()
            return int(values[0])
        except (RedisError, ConnectionError, OSError, TimeoutError) as exc:
            raise _redis_failure(exc) from exc

    async def check_rate_limits(self, ip: str, code: str) -> None:
        ip_key = self._key("rate-ip", ip)
        if await self._increment(ip_key, self.ip_window_seconds) > self.ip_limit:
            raise RedeemRateLimited(self.ip_window_seconds)
        card_key = self._key("rate-card", f"{ip}\0{code}")
        if await self._increment(card_key, self.card_window_seconds) > self.card_limit:
            raise RedeemRateLimited(self.card_window_seconds)

    async def check_counter_limit(self, scope: str, identity: str, *, limit: int, window_seconds: int) -> None:
        if await self._increment(self._key(scope, identity), window_seconds) > int(limit):
            raise RedeemRateLimited(window_seconds)

    async def challenge_required(self, ip: str) -> bool:
        key = self._key("failures", ip)
        try:
            raw = await self.redis.get(key)
        except (RedisError, ConnectionError, OSError, TimeoutError) as exc:
            raise _redis_failure(exc) from exc
        return int(raw or 0) >= self.failure_threshold

    async def record_failure(self, ip: str) -> int:
        return await self._increment(self._key("failures", ip), self.failure_window_seconds)

    async def clear_failures(self, ip: str) -> None:
        try:
            await self.redis.delete(self._key("failures", ip))
        except (RedisError, ConnectionError, OSError, TimeoutError) as exc:
            raise _redis_failure(exc) from exc

    async def acquire_admission(self, code: str) -> RedeemAdmission:
        card_key = self._key("lock", code)
        token = secrets.token_urlsafe(24)
        try:
            acquired = await self.redis.set(card_key, token, ex=self.lease_seconds, nx=True)
        except (RedisError, ConnectionError, OSError, TimeoutError) as exc:
            raise _redis_failure(exc) from exc
        if not acquired:
            raise RedeemCardBusy("该卡密正在处理中，请稍后重试")

        try:
            semaphore_acquired = await self.redis.eval(
                ACQUIRE_SEMAPHORE_SCRIPT,
                1,
                self.semaphore_key,
                token,
                self.lease_seconds,
                self.concurrency,
            )
        except (RedisError, ConnectionError, OSError, TimeoutError) as exc:
            await self._release_card_lock(card_key, token)
            raise _redis_failure(exc) from exc
        if not semaphore_acquired:
            await self._release_card_lock(card_key, token)
            raise RedeemServerBusy("当前兑换任务较多，请稍后重试")
        return RedeemAdmission(self, card_key, token)

    async def _release_card_lock(self, card_key: str, token: str) -> None:
        try:
            await self.redis.eval(RELEASE_LOCK_SCRIPT, 1, card_key, token)
        except (RedisError, ConnectionError, OSError, TimeoutError):
            return

    @asynccontextmanager
    async def admission(self, code: str) -> AsyncIterator[None]:
        lease: Optional[RedeemAdmission] = await self.acquire_admission(code)
        try:
            yield
        finally:
            await lease.release()
