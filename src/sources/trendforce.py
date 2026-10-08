"""TrendForce のメモリスポット価格。ページ上の当日値だけが取れるので、毎営業日取得して履歴を蓄積する。"""
import re

import pandas as pd
from bs4 import BeautifulSoup

from .. import http

BASE = "https://www.trendforce.com/price/"
PAGES = {"dram_spot": "dram/dram_spot", "flash_spot": "flash/flash_spot"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def parse_tables(html: str) -> list[dict]:
    """ページ内の価格表を [{"Item": ..., "<列名>": float, ...}, ...] にする。"""
    rows = []
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if not trs:
            continue
        header = [_norm(c.get_text(" ")) for c in trs[0].find_all(["th", "td"])]
        if not header or header[0] != "Item":
            continue
        for tr in trs[1:]:
            cells = [_norm(c.get_text(" ")) for c in tr.find_all(["th", "td"])]
            if len(cells) < 2:
                continue
            rec = {"Item": cells[0]}
            for name, val in zip(header[1:], cells[1:]):
                try:
                    rec[name] = float(val.replace(",", ""))
                except ValueError:
                    pass
            rows.append(rec)
    return rows


def fetch(indicators: list[dict], today: pd.Timestamp, backfill: bool = False) -> dict[str, pd.Series]:
    out = {}
    by_page: dict[str, list[dict]] = {}
    for ind in indicators:
        by_page.setdefault(ind["params"]["page"], []).append(ind)
    for page, inds in by_page.items():
        rows = parse_tables(http.get(BASE + PAGES[page]).text)
        for ind in inds:
            item, field = _norm(ind["params"]["item"]), ind["params"]["field"]
            hit = [r for r in rows if r["Item"] == item and field in r]
            if not hit:
                raise ValueError(f"TrendForce: 品目 '{item}' / 列 '{field}' が見つからない（ページ構成変更の可能性）")
            out[ind["id"]] = pd.Series({today: hit[0][field]})
    return out
