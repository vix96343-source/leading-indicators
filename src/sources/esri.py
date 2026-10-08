"""内閣府 経済社会総合研究所（ESRI）の統計。

- 機械受注統計: 毎月の公表ページの CSV（季節調整値、直近 13 か月分）。過去分は過去の公表回から集める。
  民需（船舶・電力を除く）＝いわゆる「コア機械受注」、設備投資の先行指標。
"""
import csv
import io
import re

import pandas as pd

from .. import http

JUCHU_INDEX = "https://www.esri.cao.go.jp/jp/stat/juchu/juchu.html"
JUCHU_BASE = "https://www.esri.cao.go.jp"
# 季調系列 CSV（-1.csv）の列位置: 合計, 船舶除く, 外需, 官公需, 民需, 民需(船舶除く), 民需(船舶・電力除く)
JUCHU_COLS = {"juchu_total": 4, "juchu_foreign": 6, "juchu_core": 10}
BACKFILL_FROM = 2019


def _num(s: str):
    s = s.strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_juchu_csv(text: str) -> dict[str, pd.Series]:
    """季調系列 CSV の月次の金額行（前期比の表より上）を取り出す。単位は百万円。"""
    vals = {k: {} for k in JUCHU_COLS}
    year = None
    for cells in csv.reader(io.StringIO(text)):
        if len(cells) < 11:
            continue
        if cells[1].strip():  # 「前期(月)比」以降は変化率の表
            if year is not None:
                break
            continue
        label = cells[2].strip()
        if "-" in label:  # 四半期の行（例: 2025年 7- 9月）
            continue
        m = re.match(r"(?:(\d{4})年)?\s*(\d{1,2})月$", label)
        if not m:
            continue
        if m.group(1):
            year = int(m.group(1))
        if year is None:
            continue
        month = pd.Timestamp(year, int(m.group(2)), 1)
        for key, col in JUCHU_COLS.items():
            v = _num(cells[col])
            if v is not None:
                vals[key][month] = v
    return {k: pd.Series(v, dtype=float).sort_index() for k, v in vals.items() if v}


def list_juchu_releases(html: str) -> list[str]:
    """公表ページの一覧（新しい順に並ぶ）→ 古い順の URL リスト。"""
    paths = re.findall(r'href="(/jp/stat/juchu/\d{4}/(\d{2})(\d{2})juchu\.html)"', html)
    urls = []
    for path, yy, _mm in paths:
        if 2000 + int(yy) >= BACKFILL_FROM:
            urls.append(JUCHU_BASE + path)
    return sorted(set(urls))


def fetch(indicators: list[dict], today: pd.Timestamp, backfill: bool = False) -> dict[str, pd.Series]:
    fields = {ind["params"]["field"]: ind["id"] for ind in indicators}
    out = {}

    want = [f for f in fields if f in JUCHU_COLS]
    if want:
        releases = list_juchu_releases(http.get(JUCHU_INDEX).content.decode("utf-8", "ignore"))
        # 各回の CSV は直近 13 か月分。backfill 時は 12 か月おきの回で全期間を埋め、最後に最新回で上書きする
        targets = (releases[::12] + releases[-1:]) if backfill else releases[-1:]
        merged: dict[str, pd.Series] = {}
        for page_url in targets:
            page = http.get(page_url).content.decode("utf-8", "ignore")
            m = re.search(r'href="(\d{4}juchu-1\.csv)"', page)
            if not m:
                continue
            csv_url = page_url.rsplit("/", 1)[0] + "/" + m.group(1)
            for key, s in parse_juchu_csv(http.get(csv_url).content.decode("cp932", "ignore")).items():
                merged[key] = s.combine_first(merged[key]) if key in merged else s  # 新しい回を優先
        for key in want:
            if key in merged:
                out[fields[key]] = merged[key]
    if not out:
        raise ValueError("ESRI: データが取れない（ページ構成変更の可能性）")
    return out
