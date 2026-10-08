"""内閣府のアンケート系の先行指標（毎月の公表 PDF の本文から値を読む）。

- 景気ウォッチャー調査: 先行き判断DI・現状判断DI（季節調整値）。50 が「良くも悪くもない」。
- 消費動向調査: 消費者態度指数（二人以上の世帯、季節調整値）。
どちらも時系列のファイルが無いため、通常は最新回だけ、backfill 時は過去の公表回をさかのぼって集める。
"""
import re
import unicodedata

import pandas as pd
import pymupdf

from .. import http

WATCHER_INDEX = "https://www5.cao.go.jp/keizai3/watcher_index.html"
WATCHER_BASE = "https://www5.cao.go.jp/keizai3/"
SHOUHI_INDEX = "https://www.esri.cao.go.jp/jp/stat/shouhi/shouhi.html"
SHOUHI_BASE = "https://www.esri.cao.go.jp/jp/stat/shouhi/"
BACKFILL_RELEASES = 40  # backfill でさかのぼる公表回数（約3年強）


def _pdf_text(url: str, pages: int) -> str:
    doc = pymupdf.open(stream=http.get(url).content, filetype="pdf")
    text = "\n".join(doc[i].get_text() for i in range(min(pages, doc.page_count)))
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text))  # 全角数字・ＤＩなどを半角に


def parse_watcher(text: str) -> dict[str, tuple[pd.Timestamp, float]]:
    """「令和8年9月調査結果」「9月の先行き判断DI(季節調整値)は、…の47.4 となった」→ 月と値。"""
    m = re.search(r"令和\s*(\d+)\s*年\s*(\d{1,2})\s*月調査結果", text)
    if not m:
        raise ValueError("景気ウォッチャー: 調査月が読めない")
    month = pd.Timestamp(2018 + int(m.group(1)), int(m.group(2)), 1)
    out = {}
    for key, label in (("watcher_future", "先行き判断"), ("watcher_current", "現状判断")):
        # PDF の改行で「と なった」と分かれる回がある
        v = re.search(label + r"DI\(季節調整値\)は、[^。]*?の\s*([\d.]+)\s*と\s*な", text)
        if v:
            out[key] = (month, float(v.group(1)))
    if not out:
        raise ValueError("景気ウォッチャー: DI が読めない")
    return out


def parse_shouhi(text: str) -> tuple[pd.Timestamp, float]:
    """「令和8(2026)年8月の消費者態度指数は、前月差0.6 ポイント上昇し35.5 であった」→ 月と値。"""
    m = re.search(r"\((\d{4})\)\s*年\s*(\d{1,2})\s*月の消費者態度指数は、[^。]*?([\d.]+)\s*で\s*あ\s*っ\s*た", text)
    if not m:
        raise ValueError("消費動向調査: 消費者態度指数が読めない")
    return pd.Timestamp(int(m.group(1)), int(m.group(2)), 1), float(m.group(3))


def watcher_releases(html: str) -> list[str]:
    paths = sorted(set(re.findall(r'href="((\d{4})/(\d{4})watcher/menu\.html)"', html)), key=lambda p: (p[1], p[2]))
    return [WATCHER_BASE + p[0].replace("menu.html", "watcher1.pdf") for p in paths]


def shouhi_releases(html: str) -> list[str]:
    return [SHOUHI_BASE + f for f in sorted(set(re.findall(r'href="(honbun\d{6}\.pdf)"', html)))]


def fetch(indicators: list[dict], today: pd.Timestamp, backfill: bool = False) -> dict[str, pd.Series]:
    fields = {ind["params"]["field"]: ind["id"] for ind in indicators}
    n = BACKFILL_RELEASES if backfill else 1
    vals: dict[str, dict] = {k: {} for k in fields}
    errors = []

    if {"watcher_future", "watcher_current"} & fields.keys():
        for url in watcher_releases(http.get(WATCHER_INDEX).content.decode("utf-8", "ignore"))[-n:]:
            try:
                for key, (month, v) in parse_watcher(_pdf_text(url, 2)).items():
                    if key in vals:
                        vals[key][month] = v
            except Exception as e:  # 1回分の失敗で全体を止めない
                errors.append(f"{url.rsplit('/', 2)[-2]}: {e}")

    if "consumer_confidence" in fields:
        for url in shouhi_releases(http.get(SHOUHI_INDEX).content.decode("utf-8", "ignore"))[-n:]:
            try:
                month, v = parse_shouhi(_pdf_text(url, 5))
                vals["consumer_confidence"][month] = v
            except Exception as e:
                errors.append(f"{url.rsplit('/', 1)[-1]}: {e}")

    out = {fields[k]: pd.Series(v, dtype=float).sort_index() for k, v in vals.items() if v}
    if errors:
        print("  [内閣府調査 警告] " + " / ".join(errors[:5]))
    if not out:
        raise ValueError("内閣府調査: 値が取れない " + " / ".join(errors[:3]))
    return out
