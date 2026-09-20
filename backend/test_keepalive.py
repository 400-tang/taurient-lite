"""保活线程的测试。

这一块的两个崩法都是静默的：跨零点的时段判断写错，保活会永远不触发；
在本地或测试里误启动，会让每个开发者的机器每十分钟去敲一次云上的服务。
两种情况都不会报错，所以只能靠用例守。
"""

from __future__ import annotations

import datetime as dt
import os
import threading
import unittest
from unittest import mock

from . import keepalive


def at(hour: int) -> dt.datetime:
    return dt.datetime(2026, 9, 20, hour, 30, tzinfo=dt.timezone.utc)


class TestWindow(unittest.TestCase):
    def test_normal_window(self):
        window = (9, 17)
        self.assertTrue(keepalive.within(window, at(9)))
        self.assertTrue(keepalive.within(window, at(16)))
        self.assertFalse(keepalive.within(window, at(17)))
        self.assertFalse(keepalive.within(window, at(8)))

    def test_window_wraps_past_midnight(self):
        """默认时段就是跨零点的，写成 start <= h < end 会全天为假。"""
        window = keepalive.DEFAULT_WINDOW  # (12, 4)
        for hour in (12, 18, 23, 0, 3):
            self.assertTrue(keepalive.within(window, at(hour)), hour)
        for hour in (4, 7, 11):
            self.assertFalse(keepalive.within(window, at(hour)), hour)

    def test_equal_bounds_mean_always_on(self):
        for hour in range(24):
            self.assertTrue(keepalive.within((0, 0), at(hour)))

    def test_default_window_leaves_headroom_under_the_free_quota(self):
        """free plan 每月 750 实例小时，默认时段必须留出余量。

        挂满 24 小时是 744 小时/月，几乎顶满额度——默认值绝不能是全天。
        """
        start, end = keepalive.DEFAULT_WINDOW
        hours = (end - start) % 24
        self.assertLess(hours * 31, 750)


class TestParseWindow(unittest.TestCase):
    def test_parses_pair(self):
        self.assertEqual(keepalive.parse_window("9-17"), (9, 17))

    def test_bad_values_fall_back_to_default(self):
        """拼错的环境变量应该退回默认，而不是让服务起不来。"""
        for raw in (None, "", "抓狂", "9", "9-", "-", "9-17-20", "25-4", "9-99", "-3-4"):
            with self.subTest(raw):
                self.assertEqual(keepalive.parse_window(raw), keepalive.DEFAULT_WINDOW)


class TestStart(unittest.TestCase):
    def test_no_thread_without_render_env(self):
        """本地开发绝不该起这个线程。"""
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(keepalive.start())

    def test_thread_starts_on_render(self):
        env = {"RENDER_EXTERNAL_URL": "https://example.invalid"}
        stop = threading.Event()
        with mock.patch.dict(os.environ, env, clear=True):
            thread = keepalive.start(stop)
        self.assertIsNotNone(thread)
        self.assertTrue(thread.daemon, "非守护线程会拖慢每次部署的退出")
        stop.set()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())


class TestPing(unittest.TestCase):
    def test_failure_is_swallowed(self):
        """敲不通是常态之一，不该冒异常出来。"""
        with mock.patch.object(keepalive.urllib.request, "urlopen", side_effect=OSError("down")):
            self.assertFalse(keepalive.ping("https://example.invalid"))

    def test_hits_health_on_the_given_host(self):
        seen: list[str] = []

        class Resp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake(url, timeout=None):
            seen.append(url)
            return Resp()

        with mock.patch.object(keepalive.urllib.request, "urlopen", fake):
            self.assertTrue(keepalive.ping("https://example.invalid/"))
        self.assertEqual(seen, ["https://example.invalid/health"])


class TestLoop(unittest.TestCase):
    def test_skips_outside_the_window(self):
        """时段外要跳过 ping，但线程本身不能退出——不然改时段也回不来。"""
        stop = threading.Event()
        calls: list[str] = []

        def fake_ping(url, timeout=keepalive.TIMEOUT):
            calls.append(url)
            stop.set()
            return True

        with mock.patch.object(keepalive, "ping", fake_ping):
            with mock.patch.object(keepalive, "within", return_value=False):
                thread = threading.Thread(
                    target=keepalive._loop,
                    args=("https://example.invalid", (0, 0), 0.01, stop),
                    daemon=True,
                )
                thread.start()
                threading.Timer(0.3, stop.set).start()
                thread.join(timeout=5)
        self.assertEqual(calls, [])
        self.assertFalse(thread.is_alive())

    def test_pings_inside_the_window(self):
        stop = threading.Event()
        calls: list[str] = []

        def fake_ping(url, timeout=keepalive.TIMEOUT):
            calls.append(url)
            stop.set()
            return True

        with mock.patch.object(keepalive, "ping", fake_ping):
            thread = threading.Thread(
                target=keepalive._loop,
                args=("https://example.invalid", (0, 0), 0.01, stop),
                daemon=True,
            )
            thread.start()
            thread.join(timeout=5)
        self.assertEqual(calls, ["https://example.invalid"])


if __name__ == "__main__":
    unittest.main()
