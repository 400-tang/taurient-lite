"""个股页上的「最新消息」：未经筛选的新闻标题流。

**这一层刻意不做判断。** 不读原文、不去重成事件、不分层、不写「为什么
重要」——那些是每日简报干的活，由模型来做，一天跑一两次。这里只回答
「这只票最近有什么消息」，代价是原始、嘈杂，好处是永远新鲜、覆盖任何
代码，而且成本接近零。

**所以它必须在界面上和简报明确区分开。** 同一个页面上摆着两块新闻，
一块是你自己筛过写过的，一块是机器扒来的标题，读者必须一眼分得清哪块
带判断、哪块不带。整个项目的信任基础就是标注不撒谎。

数据源是 Google News 的 RSS 搜索：免费、无鉴权、秒级响应，而且按公司名
加代码搜比任何个股新闻接口的覆盖都广。代价是噪音大——所以下面花了不少
力气在过滤和去重上。
"""

from __future__ import annotations

import datetime as dt
import html
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

ENDPOINT = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

#: 最多显示几条。这是「最近有什么消息」，不是一份档案。
MAX_ITEMS = 8

#: 超过这个天数的不显示。个股页上挂一条三个月前的标题，除了占地方
#: 没有任何作用——而且会让读者以为那是新消息。
MAX_AGE_DAYS = 14


class NewsError(RuntimeError):
    """抓取或解析失败。调用方决定是降级还是报错。"""


@dataclass(frozen=True, slots=True)
class Headline:
    """一条标题。"""

    title: str
    url: str
    source: str
    published: dt.datetime | None

    def age_label(self, now: dt.datetime | None = None) -> str:
        """相对时间。**新闻的价值随时间衰减得很快**，「3 小时前」比一个
        绝对时间戳更能让人判断该不该点进去。"""
        if self.published is None:
            return ""
        now = now or dt.datetime.now(dt.timezone.utc)
        delta = now - self.published
        minutes = int(delta.total_seconds() // 60)
        if minutes < 1:
            return "刚刚"
        if minutes < 60:
            return f"{minutes} 分钟前"
        hours = minutes // 60
        if hours < 24:
            return f"{hours} 小时前"
        return f"{hours // 24} 天前"


def build_query(symbol: str, name: str = "") -> str:
    """拼搜索词。**有公司名就只用公司名，不要把代码 OR 进去。**

    很多代码本身是常用英文词：A（Agilent）、ON（安森美）、ALL、IT、CAR。
    把它们 OR 进查询，搜索引擎会把一切含这个词的文章都算命中——实测
    搜 ``"Agilent Technologies" OR "A" stock`` 返回的全是「全球股市会不会
    崩盘」这类泛泛的大盘新闻，一条 Agilent 的都没有。

    去掉代码之后同样三只票（A / ON / NVDA）返回的全部是本公司新闻。
    代码只在拿不到公司名时兜底——那种情况下它是唯一的线索，再嘈杂也
    比没有强。
    """
    symbol = symbol.upper().strip()
    name = (name or "").strip()
    # 公司名里的法律后缀对搜索没帮助，还会稀释关键词。
    #
    # **要反复剥到不再变化**，不能只走一趟：「SK hynix Inc. ADR」先被
    # 剥掉 ADR 变成「SK hynix Inc.」，而这时 Inc. 那一轮已经过去了。
    changed = True
    while changed:
        changed = False
        for suffix in (" Inc.", " Inc", " Corporation", " Corp.", " Corp",
                       " Ltd.", " Ltd", " plc", " PLC", " Co.", " Company",
                       " ADR", " Common Stock"):
            if name.endswith(suffix):
                name = name[: -len(suffix)].strip()
                changed = True
    term = name or symbol
    return urllib.parse.quote(f'"{term}" stock')


def _text(node: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", node, re.S)
    if not m:
        return ""
    return html.unescape(m.group(1)).replace("<![CDATA[", "").replace("]]>", "").strip()


def _parse_date(raw: str) -> dt.datetime | None:
    """RFC 822 时间。解析不了就返回 None，不猜——一条时间不明的新闻
    宁可不显示时间，也不要显示一个编出来的。"""
    if not raw:
        return None
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            parsed = dt.datetime.strptime(raw.strip(), fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            return parsed
        except ValueError:
            continue
    return None


def _split_source(title: str) -> tuple[str, str]:
    """Google News 的标题末尾带 ``- 来源``，拆出来分开显示。

    只拆最后一个「 - 」：标题里本来就可能有连字符（"AI - 的下一步"），
    从前面拆会把标题腰斩。
    """
    if " - " in title:
        head, _, tail = title.rpartition(" - ")
        if head and len(tail) < 40:
            return head.strip(), tail.strip()
    return title, ""


def _norm(title: str) -> str:
    """用于去重的归一化标题：去掉标点与大小写差异。"""
    return re.sub(r"[^a-z0-9一-鿿]+", "", title.lower())


def parse_feed(
    xml: str,
    *,
    limit: int = MAX_ITEMS,
    max_age_days: int = MAX_AGE_DAYS,
    now: dt.datetime | None = None,
) -> tuple[Headline, ...]:
    """从 RSS 里取出标题，去重并按时间过滤。

    **去重是必须的。** 同一件事十家媒体各发一条，不去重的话八个位置会被
    一个事件占满，而读者要的是「最近有哪些事」，不是「这件事有多少家报」。
    判据是归一化后的标题前缀重合——不做语义判断，那是模型的活。
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(days=max_age_days)

    out: list[Headline] = []
    seen: list[str] = []

    for block in re.findall(r"<item>(.*?)</item>", xml, re.S):
        title, source = _split_source(_text(block, "title"))
        if not title:
            continue
        published = _parse_date(_text(block, "pubDate"))
        if published is not None and published < cutoff:
            continue

        key = _norm(title)[:48]
        if not key or any(key[:40] == s[:40] for s in seen):
            continue
        seen.append(key)

        out.append(
            Headline(
                title=title,
                url=_text(block, "link"),
                source=source or _text(block, "source"),
                published=published,
            )
        )
        if len(out) >= limit:
            break

    return tuple(out)


def fetch_headlines(
    symbol: str, *, name: str = "", limit: int = MAX_ITEMS, timeout: float = 10.0
) -> tuple[Headline, ...]:
    """抓一只票的最新消息。网络或解析失败抛 :class:`NewsError`。"""
    url = ENDPOINT.format(query=build_query(symbol, name))
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            xml = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise NewsError(f"{symbol}：取新闻失败（{exc}）") from exc
    return parse_feed(xml, limit=limit)
