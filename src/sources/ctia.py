"""中钨在线（ctia.com.cn）の毎日の「钨市场行情」記事からタングステン価格を読む。

記事は WordPress の検索 API で取れる。価格は「33-36万元/标吨」のような幅で書かれるので中値を使う。
サイトは無断転載・使用・配布を禁じているため、indicators.yaml で restricted: true にして公開版では扱わない。
"""
import html as htmllib
import re
from urllib.parse import quote

import pandas as pd

from .. import http
from .yf import clean

API = "https://www.ctia.com.cn/wp-json/wp/v2/posts?search={q}&per_page={n}&page={page}&_fields=date,link,content"
NUM = r"(\d+(?:\.\d+)?)(?:\s*[-~～－]\s*(\d+(?:\.\d+)?))?"
PATTERNS = {
    "w_concentrate": r"(?<!白)钨精矿[^。]{0,40}?" + NUM + r"\s*万元/标?吨",  # 高品位タングステン精鉱 55-65%（万元/トン）
    "w_apt": r"仲钨酸铵（APT）[^。]*?" + NUM + r"\s*万元/吨",       # APT（万元/トン）
    "w_powder": r"(?<!碳化)钨粉(?:价格|报价)?[^。，、]{0,20}?" + NUM + r"\s*元/(?:千克|公斤)",  # タングステン粉（元/kg）
    "w_ferro": r"70钨铁[^。]*?" + NUM + r"\s*万元/吨",               # フェロタングステン 70%（万元/トン）
    "w_apt_eu": r"欧洲APT报价\s*" + NUM + r"\s*美元/吨度",            # 欧州 APT（ドル/mtu）
}


def _mid(a: str, b: str | None) -> float:
    return (float(a) + float(b)) / 2 if b else float(a)


def parse_article(text: str) -> tuple[pd.Timestamp, dict[str, float]] | None:
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日钨市场行情", text)
    if not m:
        return None  # 月次の総括記事などは対象外
    day = pd.Timestamp(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    vals = {}
    for key, pat in PATTERNS.items():
        v = re.search(pat, text)
        if v:
            vals[key] = _mid(v.group(1), v.group(2))
    return (day, vals) if vals else None


def _plain(rendered: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", rendered)))


def fetch(indicators: list[dict], today: pd.Timestamp, backfill: bool = False) -> dict[str, pd.Series]:
    fields = {ind["params"]["field"]: ind["id"] for ind in indicators}
    vals = {k: {} for k in fields}
    pages, per = (8, 100) if backfill else (1, 10)
    for page in range(1, pages + 1):
        try:
            posts = http.get(API.format(q=quote("钨市场行情"), n=per, page=page)).json()
        except Exception:
            break  # ページ数の上限を超えると 400 が返る
        if not posts:
            break
        for p in posts:
            got = parse_article(_plain(p["content"]["rendered"]))
            if not got:
                continue
            day, v = got
            for k in fields:
                if k in v:
                    vals[k].setdefault(day, v[k])
    # 記事の文脈を読み違えた単発の外れ値（翌日に戻るもの）は除く
    out = {fields[k]: clean(pd.Series(v, dtype=float).sort_index()) for k, v in vals.items() if v}
    if not out:
        raise ValueError("中钨在线: 価格が読めない（記事の書式変更の可能性）")
    return out
