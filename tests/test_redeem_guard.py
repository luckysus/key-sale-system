import time
import unittest

from backend import redeem_guard as redeem_guard_module
from backend.redeem_guard import (
    ACQUIRE_SEMAPHORE_SCRIPT,
    RedeemCardBusy,
    RedeemGuard,
    RedeemGuardUnavailable,
    RedeemRateLimited,
    RedeemServerBusy,
)


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.commands = []

    def incr(self, key):
        self.commands.append(("incr", key))
        return self

    def expire(self, key, seconds, *, nx=False):
        self.commands.append(("expire", key, seconds, nx))
        return self

    async def execute(self):
        results = []
        for command in self.commands:
            if command[0] == "incr":
                results.append(await self.redis.incr(command[1]))
            elif command[0] == "expire":
                results.append(await self.redis.expire(command[1], command[2], nx=command[3]))
        return results


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.expires = {}
        self.sorted_sets = {}
        self.available = True

    def _purge(self, key):
        if self.expires.get(key, float("inf")) <= time.time():
            self.values.pop(key, None)
            self.sorted_sets.pop(key, None)
            self.expires.pop(key, None)

    def _require_available(self):
        if not self.available:
            raise ConnectionError("redis unavailable")

    async def ping(self):
        self._require_available()
        return True

    def pipeline(self, transaction=True):
        return FakePipeline(self)

    async def incr(self, key):
        self._require_available()
        self._purge(key)
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    async def expire(self, key, seconds, *, nx=False):
        self._require_available()
        if nx and key in self.expires:
            return False
        self.expires[key] = time.time() + int(seconds)
        return True

    async def get(self, key):
        self._require_available()
        self._purge(key)
        value = self.values.get(key)
        if value is None or isinstance(value, bytes):
            return value
        return str(value).encode()

    async def delete(self, key):
        self._require_available()
        existed = key in self.values or key in self.sorted_sets
        self.values.pop(key, None)
        self.sorted_sets.pop(key, None)
        self.expires.pop(key, None)
        return int(existed)

    async def set(self, key, value, ex=None, nx=False):
        self._require_available()
        self._purge(key)
        if nx and key in self.values:
            return False
        self.values[key] = value.encode() if isinstance(value, str) else value
        if ex:
            self.expires[key] = time.time() + int(ex)
        return True

    async def zrem(self, key, member):
        self._require_available()
        members = self.sorted_sets.get(key, {})
        return int(members.pop(member, None) is not None)

    async def eval(self, script, numkeys, *args):
        self._require_available()
        key = args[0]
        if "ZREMRANGEBYSCORE" in script:
            token, ttl, limit = args[1:]
            now_value = time.time()
            members = self.sorted_sets.setdefault(key, {})
            for member, score in list(members.items()):
                if score <= float(now_value):
                    members.pop(member, None)
            if len(members) >= int(limit):
                return 0
            members[token] = now_value + int(ttl)
            self.expires[key] = time.time() + int(ttl)
            return 1
        token = args[1]
        current = await self.get(key)
        expected = token.encode() if isinstance(token, str) else token
        if current == expected:
            return await self.delete(key)
        return 0


class RedeemGuardTest(unittest.IsolatedAsyncioTestCase):
    def make_guard(self, redis=None, **overrides):
        return RedeemGuard(
            redis or FakeRedis(),
            ip_limit=overrides.get("ip_limit", 20),
            ip_window_seconds=60,
            card_limit=overrides.get("card_limit", 5),
            card_window_seconds=300,
            failure_threshold=overrides.get("failure_threshold", 5),
            failure_window_seconds=600,
            concurrency=overrides.get("concurrency", 10),
            lease_seconds=210,
            key_prefix="test:redeem",
        )

    async def test_rate_limit_rejects_request_over_limit(self):
        guard = self.make_guard(ip_limit=2, card_limit=10)
        await guard.check_rate_limits("1.2.3.4", "AAAA-BBBB-CCCC-DDDD")
        await guard.check_rate_limits("1.2.3.4", "AAAA-BBBB-CCCC-DDDD")
        with self.assertRaises(RedeemRateLimited):
            await guard.check_rate_limits("1.2.3.4", "AAAA-BBBB-CCCC-DDDD")

    async def test_rate_limit_keys_do_not_contain_ip_or_card(self):
        redis = FakeRedis()
        guard = self.make_guard(redis=redis)
        await guard.check_rate_limits("1.2.3.4", "AAAA-BBBB-CCCC-DDDD")
        joined = " ".join(redis.values)
        self.assertNotIn("1.2.3.4", joined)
        self.assertNotIn("AAAA-BBBB-CCCC-DDDD", joined)

    async def test_generic_counter_rejects_request_over_limit(self):
        guard = self.make_guard()
        await guard.check_counter_limit("admin-login-ip", "1.2.3.4", limit=2, window_seconds=300)
        await guard.check_counter_limit("admin-login-ip", "1.2.3.4", limit=2, window_seconds=300)
        with self.assertRaises(RedeemRateLimited) as raised:
            await guard.check_counter_limit("admin-login-ip", "1.2.3.4", limit=2, window_seconds=300)
        self.assertEqual(raised.exception.retry_after, 300)

    async def test_generic_counter_hashes_identity_and_sets_ttl(self):
        redis = FakeRedis()
        guard = self.make_guard(redis=redis)
        await guard.check_counter_limit("admin-login-user", "private-admin", limit=50, window_seconds=900)
        [key] = list(redis.values)
        self.assertNotIn("private-admin", key)
        self.assertGreater(redis.expires[key], time.time() + 890)

    async def test_generic_counter_does_not_refresh_ttl_after_first_increment(self):
        redis = FakeRedis()
        guard = self.make_guard(redis=redis)
        await guard.check_counter_limit("admin-login-user", "private-admin", limit=2, window_seconds=900)
        [key] = list(redis.values)
        original_expiry = time.time() + 60
        redis.expires[key] = original_expiry

        await guard.check_counter_limit("admin-login-user", "private-admin", limit=2, window_seconds=900)
        self.assertEqual(redis.expires[key], original_expiry)
        with self.assertRaises(RedeemRateLimited):
            await guard.check_counter_limit("admin-login-user", "private-admin", limit=2, window_seconds=900)
        self.assertEqual(redis.expires[key], original_expiry)

    async def test_generic_counter_redis_failure_is_fail_closed(self):
        redis = FakeRedis()
        redis.available = False
        guard = self.make_guard(redis=redis)
        with self.assertRaises(RedeemGuardUnavailable):
            await guard.check_counter_limit("admin-login-ip", "1.2.3.4", limit=30, window_seconds=300)

    async def test_failures_require_challenge_at_threshold_and_clear(self):
        guard = self.make_guard(failure_threshold=2)
        self.assertFalse(await guard.challenge_required("1.2.3.4"))
        await guard.record_failure("1.2.3.4")
        self.assertFalse(await guard.challenge_required("1.2.3.4"))
        await guard.record_failure("1.2.3.4")
        self.assertTrue(await guard.challenge_required("1.2.3.4"))
        await guard.clear_failures("1.2.3.4")
        self.assertFalse(await guard.challenge_required("1.2.3.4"))

    async def test_same_card_lock_is_exclusive(self):
        guard = self.make_guard()
        async with guard.admission("AAAA-BBBB-CCCC-DDDD"):
            with self.assertRaises(RedeemCardBusy):
                async with guard.admission("AAAA-BBBB-CCCC-DDDD"):
                    pass

    async def test_global_concurrency_limit_is_enforced(self):
        guard = self.make_guard(concurrency=2)
        first = await guard.acquire_admission("AAAA-BBBB-CCCC-DDD1")
        second = await guard.acquire_admission("AAAA-BBBB-CCCC-DDD2")
        with self.assertRaises(RedeemServerBusy):
            await guard.acquire_admission("AAAA-BBBB-CCCC-DDD3")
        await first.release()
        third = await guard.acquire_admission("AAAA-BBBB-CCCC-DDD3")
        await third.release()
        await second.release()

    async def test_rate_limit_redis_failure_is_fail_closed(self):
        redis = FakeRedis()
        redis.available = False
        guard = self.make_guard(redis=redis)
        with self.assertRaises(RedeemGuardUnavailable):
            await guard.check_rate_limits("1.2.3.4", "AAAA-BBBB-CCCC-DDDD")

    async def test_admission_redis_failure_is_fail_closed(self):
        redis = FakeRedis()
        redis.available = False
        guard = self.make_guard(redis=redis)
        with self.assertRaises(RedeemGuardUnavailable):
            await guard.acquire_admission("AAAA-BBBB-CCCC-DDDD")

    def test_semaphore_uses_redis_time_as_shared_clock(self):
        self.assertIn("redis.call('TIME')", ACQUIRE_SEMAPHORE_SCRIPT)

    def test_lease_must_cover_timeout_plus_safety_margin(self):
        validate = getattr(redeem_guard_module, "validate_lease_seconds", None)
        self.assertTrue(callable(validate), "validate_lease_seconds is missing")
        self.assertEqual(validate(210, 180), 210)
        with self.assertRaises(ValueError):
            validate(180, 180)
        with self.assertRaises(ValueError):
            validate(209, 180)


if __name__ == "__main__":
    unittest.main()
