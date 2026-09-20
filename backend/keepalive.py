"""自己定期敲一下自己的 ``/health``，免得 Render 把免费实例停掉。

**要解决的是什么。** Render 的 free plan 上，一个 web service 连续 15
分钟没有收到请求就会被停机；下次有人访问时要冷启动几十秒，这期间
Render 的边缘层发给访客的是它自己那个转圈页面。那个页面不可自定义——
服务还没起来，我们没有任何代码在跑，也就没有地方去渲染别的东西。所以
这一层不去替换等待页，而是让等待根本不发生。

**为什么由服务自己来敲。** 外部的 ping 服务（UptimeRobot 之类）更标准，
还能在服务真的挂掉时叫醒它；但那需要另开一个账号，配置散落在仓库之外。
这里选的是把它留在代码里：``RENDER_EXTERNAL_URL`` 是 Render 注入的公网
地址，从容器里请求它会绕一圈回到 Render 的边缘层，对计时器来说就是一次
正常的外部访问。代价是**它只能防停机，不能自我唤醒**——真被停掉之后，
容器里没有进程在跑，这个线程也就不存在了。

**为什么要分时段。** free plan 是每月 750 实例小时，全账号共享。挂满
24 小时，31 天就是 744 小时，几乎顶满额度，以后再开第二个免费服务会
双双在月底被停。默认只保活 :data:`DEFAULT_WINDOW` 那段（美西 05:00–21:00），
一个月约 500 小时，留下余量；深夜访问仍然会冷启动，那是刻意换来的。

**所有失败都咽掉。** 保活是锦上添花。敲不通的时候正确的反应是下次再敲，
而不是把一个后台线程的异常冒到日志里吓人，更不该影响正在处理的请求。
"""

from __future__ import annotations

import datetime as dt
import os
import threading
import urllib.request

#: 敲击间隔。必须明显小于 Render 的 15 分钟停机阈值——取 10 分钟，
#: 留出一次失败的余量：偶尔漏掉一次也还有下一次赶在 15 分钟之前。
PING_EVERY = 600.0

#: 请求超时。这是打给自己的一个常数路由，正常是毫秒级；给到 10 秒
#: 纯粹是为了容忍偶发的网络抖动，超了就当这次没敲成。
TIMEOUT = 10.0

#: 保活时段，UTC 的 [start, end)，跨零点。12:00–04:00 UTC = 美西
#: 05:00–21:00：覆盖盘前、整个交易日和当天傍晚。用环境变量
#: ``KEEPALIVE_WINDOW``（形如 ``"12-4"``）可以改；设成 ``"0-0"``
#: 表示全天保活。
DEFAULT_WINDOW = (12, 4)


def parse_window(raw: str | None) -> tuple[int, int]:
    """解析 ``"12-4"`` 这样的时段。格式不对就退回默认值。

    **坏配置不该让保活整个失效**，更不该让服务起不来——一个拼错的环境
    变量的正确后果是「按默认时段保活」，而不是页面 500。
    """
    if not raw:
        return DEFAULT_WINDOW
    try:
        start, end = (int(part) for part in raw.split("-", 1))
    except ValueError:
        return DEFAULT_WINDOW
    if not (0 <= start <= 23 and 0 <= end <= 23):
        return DEFAULT_WINDOW
    return start, end


def within(window: tuple[int, int], now: dt.datetime) -> bool:
    """此刻是否在保活时段内。

    **时段允许跨零点**（12–4 表示 12:00 到次日 04:00），所以不能直接
    写 ``start <= hour < end``：那样 12–4 会永远为假，保活静默失灵。
    起止相同表示全天。
    """
    start, end = window
    if start == end:
        return True
    hour = now.hour
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def ping(url: str, timeout: float = TIMEOUT) -> bool:
    """敲一次，成功返回 True。任何失败都只是返回 False。"""
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/health", timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def _loop(url: str, window: tuple[int, int], every: float, stop: threading.Event) -> None:
    # 先等一个间隔再开始：进程刚起来的时候本来就有请求在跑（Render 的
    # 健康检查、触发冷启动的那位访客），这时候再敲一下纯属多余。
    while not stop.wait(every):
        if within(window, dt.datetime.now(dt.timezone.utc)):
            ping(url)


def start(stop: threading.Event | None = None) -> threading.Thread | None:
    """按环境变量决定是否启动保活线程，没启动就返回 None。

    **本地开发和测试里必须是空操作。** 判据是 ``RENDER_EXTERNAL_URL``
    存不存在——这个变量只有 Render 会注入，于是「在云上」这件事不需要
    另设一个开关来声明，也就不会出现开关与实际环境不一致的情况。
    """
    url = os.environ.get("RENDER_EXTERNAL_URL", "").strip()
    if not url:
        return None
    thread = threading.Thread(
        target=_loop,
        args=(url, parse_window(os.environ.get("KEEPALIVE_WINDOW")), PING_EVERY,
              stop or threading.Event()),
        name="keepalive",
        # 守护线程：进程要退出时不必等它醒过来，否则每次部署都要多拖
        # 最多十分钟才肯死。
        daemon=True,
    )
    thread.start()
    return thread
