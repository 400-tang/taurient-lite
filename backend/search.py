"""股票搜索：按公司名找代码，供自选股面板的自动补全使用。

**为什么需要它。** 原来的自选股输入框只接受精确的股票代码，对不熟悉
代码的人几乎不可用——想加苹果得先知道是 AAPL。更糟的是原来的校验
只看格式不看真伪：输入 ``APPLE``、``GOOGLE``、``ZZZZZ`` 全部通过，
静默存进数据库，页面上出现一个看着正常、却永远匹配不到任何新闻的芯片。
这个模块同时解决这两件事——**能按名字找，而且找到的一定是真实存在的**。

**两个数据源合并，各补各的短板。** Yahoo 的 search 端点认得品牌别名——
``google`` 能查到 Alphabet，而官方名单里 GOOGL 的名称是「Alphabet Inc.」，
压根不含 Google 这个词。但 Yahoo 只做前缀/子串匹配，不容错：``gogle``、
``nvdia``、``microsft`` 全部返回空，而 ``gool`` 更糟——它返回 GOOLF，
一个真实存在但完全不相干的 OTC 票。**打错一个字母，拿到一个看着像模像样
的错答案**，这跟静默失败是同一类问题。

所以再叠一层本地索引（``data/symbols.txt``，美国交易所官方目录，由
``scan_momentum.py`` 重建名单时顺带产出）：它既是**真伪校验闸**——
Yahoo 的结果凡是不在这份名单里的一律丢弃，GOOLF 正是这样被挡掉的——
也是**容错来源**，用 difflib 对代码和公司名各比一次。排序上再用
``data/universe.txt``（流动性达标的那批）加权，因为纯字符串距离不知道
哪家公司更可能被搜：``TELSA`` 在编辑距离上更接近 TLSA（Tiziana Life
Sciences）而不是 TSLA，只有成交额这个信号能把 TSLA 拉回前面。

**返回结果噪音极大。** 搜 ``apple`` 会带出德国、维也纳、巴西的同名挂牌，
以及 ETF 和代币化股票。自选股面板要的是美股正股，所以按 :func:`is_us_equity`
过滤——带交易所后缀的（``.DE``/``.VI``/``.BA``）一律排除。

**非 ASCII 查询直接返回空。** Yahoo 对这类查询回 HTTP 400，原样送上去会
让「查不到」变成「上游报错」，前端进而显示成「搜索暂时不可用」——把一个
正常的空结果误报成故障。这里短路掉，不是为了支持别的语言，是为了不撒谎。

网络与解析照例分开：:func:`parse_results` 是纯函数，测试注入一段假响应
就能覆盖全部过滤分支，不联网也不受对方限流影响。
"""

from __future__ import annotations

import difflib
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

ENDPOINT = (
    "https://query1.finance.yahoo.com/v1/finance/search"
    "?q={}&quotesCount={}&newsCount=0"
)

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

#: 返回给前端的条数上限。下拉框里超过八条就没人看了，
#: 而且更长的列表意味着更差的匹配质量，不如让用户把查询写具体一点。
MAX_RESULTS = 8


class SearchError(RuntimeError):
    """搜索失败。调用方决定是降级还是报错。"""


@dataclass(frozen=True, slots=True)
class Match:
    """一条搜索结果。"""

    symbol: str
    name: str
    exchange: str

    def as_dict(self) -> dict[str, str]:
        return {"symbol": self.symbol, "name": self.name, "exchange": self.exchange}


def normalise(query: str) -> str:
    """整理用户输入。无法送给上游的查询在这里被归零。

    非 ASCII 直接判空而不是原样上送：Yahoo 对这类查询返回 HTTP 400，
    送上去只会把「没有结果」变成「上游故障」。
    """
    text = (query or "").strip()
    if not text or not text.isascii():
        return ""
    return text


# ------------------------------------------------------------------ 本地索引
#
# `data/symbols.txt` 是美国交易所的官方代码目录（由 scan_momentum.py
# 重建名单时顺带产出），`data/universe.txt` 是其中流动性达标的那批。
# 前者回答「这个代码存不存在」，后者回答「用户更可能是在找哪一只」。

INDEX_FILE = Path(__file__).resolve().parent.parent / "data" / "symbols.txt"
LIQUID_FILE = Path(__file__).resolve().parent.parent / "data" / "universe.txt"

#: 公司名里不参与匹配的通用词。留着它们会让「INC」「CORP」这类词
#: 在模糊比对里制造大量假匹配。
STOPWORDS = frozenset(
    {"INC", "CORP", "CORPORATION", "COMPANY", "CO", "LTD", "PLC",
     "GROUP", "HOLDINGS", "THE", "SA", "NV", "CLASS", "COMMON", "STOCK"}
)

#: 模糊匹配的相似度下限，以及流动性达标能拿到的加分。
#: 加分存在的理由：纯字符串距离不知道哪家公司更可能被搜——``TELSA``
#: 在编辑距离上更接近 TLSA（Tiziana Life Sciences）而不是 TSLA，
#: 只有「谁的成交额够大」这个信号能把 TSLA 拉回前面。
FUZZY_CUTOFF = 0.6
LIQUID_BONUS = 0.15

#: 模糊匹配最多补几条。补满 8 条会把勉强过线的垃圾也塞进来——
#: 下拉框里一条看着莫名其妙的结果，比少一条更伤信任。
MAX_FUZZY = 4

#: Yahoo 已经给出这么多结果时就不再补模糊匹配。
#: 上游看懂了查询的情况下，容错纯属添乱：搜 ``apple`` 本来干干净净的
#: AAPL/APLE，补上 AMAT、AIT 只会让人怀疑这个搜索到底靠不靠谱。
#: 容错要用在上游没看懂的时候——那才是打错字的场景。
FUZZY_WHEN_FEWER_THAN = 3

_INDEX: dict[str, str] | None = None
_LIQUID: frozenset[str] | None = None
#: (代码, 名字首词, 是否流动性达标)，随索引一次性算好。
#: 放在循环里现算会让每次查询多花一百多毫秒。
_ROWS: list[tuple[str, str, bool]] | None = None


def clean_name(raw: str) -> str:
    """把官方名称里的证券类型后缀去掉：``Apple Inc. - Common Stock`` → ``Apple Inc.``"""
    return raw.split(" - ")[0].strip()


def head_word(name: str) -> str:
    """公司名里第一个有辨识度的词。``Microsoft Corporation`` → ``MICROSOFT``。

    模糊匹配拿它跟用户输入比，``microsft`` 才找得到 MSFT——只比代码的话
    这个输入会匹配到一堆无关的四字母代码。
    """
    core = clean_name(name).replace(",", " ").replace(".", " ")
    for word in core.upper().split():
        if word not in STOPWORDS:
            return word
    return core.upper().strip()


def load_index() -> dict[str, str]:
    """读取代码到名称的索引。读不到就返回空字典——搜索退化成纯 Yahoo，
    仍然可用，只是没有容错和真伪校验。"""
    global _INDEX
    if _INDEX is None:
        rows: dict[str, str] = {}
        try:
            for line in INDEX_FILE.read_text(encoding="utf-8").splitlines():
                symbol, _, name = line.partition("|")
                if symbol and name:
                    rows[symbol.strip().upper()] = name.strip()
        except OSError:
            rows = {}
        _INDEX = rows
    return _INDEX


def load_liquid() -> frozenset[str]:
    global _LIQUID
    if _LIQUID is None:
        try:
            _LIQUID = frozenset(
                ln.strip().upper()
                for ln in LIQUID_FILE.read_text(encoding="utf-8").splitlines()
                if ln.strip()
            )
        except OSError:
            _LIQUID = frozenset()
    return _LIQUID


def _rows(index: dict[str, str] | None = None) -> list[tuple[str, str, bool]]:
    """``(代码, 名字首词, 是否流动性达标)``。首词预先算好——放在查询循环里
    对上万只现算，每次查询要多花一百多毫秒。"""
    if index is not None:
        liquid = load_liquid()
        return [(s, head_word(n), s in liquid) for s, n in index.items()]

    global _ROWS
    if _ROWS is None:
        liquid = load_liquid()
        _ROWS = [
            (symbol, head_word(name), symbol in liquid)
            for symbol, name in load_index().items()
        ]
    return _ROWS


def fuzzy_symbols(
    term: str,
    *,
    limit: int,
    index: dict[str, str] | None = None,
    exclude: set[str] | None = None,
) -> list[str]:
    """在本地索引里做容错匹配，返回代码列表，最像的排前面。

    代码和公司名各比一次取较高分：``gool`` 靠代码接近 GOOGL，
    ``microsft`` 靠名字接近 MICROSOFT，两条路都需要。
    """
    rows = _rows(index)
    if limit <= 0 or not rows:
        return []

    needle = term.strip().upper()
    skip = exclude or set()
    matcher = difflib.SequenceMatcher()
    matcher.set_seq2(needle)

    scored: list[tuple[float, str]] = []
    for symbol, head, is_liquid in rows:
        if symbol in skip:
            continue
        best = 0.0
        for candidate in (symbol, head):
            matcher.set_seq1(candidate)
            # 两级快速上界，避免对上万个候选都跑完整的比对
            if matcher.real_quick_ratio() <= best or matcher.quick_ratio() <= best:
                continue
            ratio = matcher.ratio()
            if ratio > best:
                best = ratio
        if best >= FUZZY_CUTOFF:
            scored.append((best + (LIQUID_BONUS if is_liquid else 0.0), symbol))

    scored.sort(reverse=True)
    return [symbol for _, symbol in scored[:limit]]


def is_us_equity(row: dict[str, Any]) -> bool:
    """只留美股正股。

    带交易所后缀的（``AAPL.VI``、``NVD.DE``、``AAPLC.BA``）是同一家公司
    在别国的挂牌，加进自选股既查不到对应的美股新闻，价格口径也不同。
    ETF 与代币化股票同理排除——这个面板的用途是跟踪个股新闻。
    """
    if row.get("quoteType") != "EQUITY":
        return False
    symbol = str(row.get("symbol") or "")
    if not symbol or "." in symbol or "-" in symbol:
        return False
    return bool(row.get("shortname") or row.get("longname"))


def parse_results(payload: object, *, limit: int = MAX_RESULTS) -> list[Match]:
    """从 Yahoo 的响应里取出可用的结果。纯函数。"""
    if not isinstance(payload, dict):
        raise SearchError(f"响应不是一个对象，实际是 {type(payload).__name__}")

    quotes = payload.get("quotes")
    if not isinstance(quotes, list):
        return []

    seen: set[str] = set()
    out: list[Match] = []
    for row in quotes:
        if not isinstance(row, dict) or not is_us_equity(row):
            continue
        symbol = str(row["symbol"]).upper()
        if symbol in seen:
            continue
        seen.add(symbol)
        out.append(
            Match(
                symbol=symbol,
                name=str(row.get("shortname") or row.get("longname")).strip(),
                exchange=str(row.get("exchDisp") or "").strip(),
            )
        )
        if len(out) >= limit:
            break
    return out


def _yahoo(term: str, limit: int, fetcher, timeout: float) -> list[Match]:
    url = ENDPOINT.format(urllib.parse.quote(term), max(limit * 3, 10))
    if fetcher is not None:
        return parse_results(fetcher(url), limit=limit)
    request = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except Exception as exc:  # noqa: BLE001 - 上游什么都可能抛，统一转成本模块的错误
        raise SearchError(f"搜索 {term!r} 失败：{exc}") from exc
    return parse_results(payload, limit=limit)


def search(
    query: str,
    *,
    limit: int = MAX_RESULTS,
    fetcher: Callable[..., object] | None = None,
    timeout: float = 10.0,
) -> list[Match]:
    """按名字或代码搜股票。查询为空时返回空列表，不去打扰上游。

    两个来源合并，各补各的短板：

    * **Yahoo** 认得品牌别名——``google`` 能查到 Alphabet，而官方名单里
      GOOGL 的名称是「Alphabet Inc.」，压根不含 Google 这个词。
    * **本地索引**容错——Yahoo 只做前缀/子串匹配，``gogle``、``nvdia``、
      ``microsft`` 全部返回空，而 ``gool`` 更糟：它返回 GOOLF，一个真实
      存在但完全不相干的 OTC 票。打错一个字母，拿到一个看着像模像样的
      错答案，这跟静默失败是同一类问题。

    Yahoo 的结果还会**被本地索引过滤一遍**：不在美国交易所官方名单里的
    一律丢弃。GOOLF 正是这样被挡掉的。
    """
    term = normalise(query)
    if not term:
        return []

    index = load_index()
    try:
        rows = _yahoo(term, limit, fetcher, timeout)
    except SearchError:
        # 上游挂了不代表搜不出东西——本地索引还在，先用它顶上。
        # 完全查不到时才把错误抛出去，让前端知道是真的坏了。
        rows = []
        if not index:
            raise

    if index:
        rows = [m for m in rows if m.symbol in index]

    # 输入本身就是一个真实代码：放首位。但**冷门代码仍然要给容错提示**——
    # 打 GOOL 的人多半想要 GOOGL（GOOL 是一只 2 倍做多 GOOGL 的杠杆 ETF），
    # 直接认定他要的就是这只、并且不提 GOOGL，等于替他做了一个他没做的决定。
    # 反过来打对 AAPL 的人不需要看到 AAP、AAL，那只制造犹豫。
    # 分界线用流动性：知名标的按原样接受，冷门的附上「你是不是想找」。
    exact = term.upper()
    if exact in index:
        rows = [m for m in rows if m.symbol != exact]
        rows.insert(0, Match(exact, clean_name(index[exact]), ""))
        if exact in load_liquid():
            return rows[:limit]

    seen = {m.symbol for m in rows}
    room = min(limit - len(rows), MAX_FUZZY) if len(rows) < FUZZY_WHEN_FEWER_THAN else 0
    if room > 0:
        for symbol in fuzzy_symbols(term, limit=room, index=index, exclude=seen):
            rows.append(Match(symbol=symbol, name=clean_name(index[symbol]), exchange=""))
    return rows[:limit]


def resolve(symbol: str, *, fetcher: Callable[..., object] | None = None) -> Match | None:
    """确认一个代码真实存在，返回它的规范形态。

    这是修掉「``APPLE`` 也能存进自选股」那个静默失败的关键：添加之前
    必须解析成功，解析不出来就不让加。
    """
    wanted = (symbol or "").strip().upper()
    if not wanted:
        return None
    for match in search(wanted, fetcher=fetcher):
        if match.symbol == wanted:
            return match
    return None
