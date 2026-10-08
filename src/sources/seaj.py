"""日本半導体製造装置協会（SEAJ）の日本製半導体製造装置 販売高（3か月移動平均の速報値）。

統計ページのプレスリリース PDF には直近6か月分が載る。毎月取得して履歴を蓄積する。
SEAJ は資料の無断転載を禁止しているため、indicators.yaml では restricted: true にしている。
"""
import re

import pymupdf as fitz
import pandas as pd

from .. import http, store

STAT_URL = "https://www.seaj.or.jp/statistics/"
ROW_RE = re.compile(r"(\d{4})/(\d{1,2})(?:\s*\([^)]*\))?\s+([\d,]+)\s+(-?[\d.]+)%\s+(-?[\d.]+)%")


def parse_release(text: str) -> tuple[pd.Series, pd.Series]:
    """PDF テキスト → (掲載月の販売高, 前年比から逆算した前年同月の販売高)。単位は百万円。

    前年同月の値は PDF に無いが、逆算して埋めると初回から前年比を出せる。
    """
    flat = re.sub(r"\s+", " ", text)
    rows, implied = {}, {}
    for y, m, v, _mom, yoy in ROW_RE.findall(flat):
        month, value = pd.Timestamp(int(y), int(m), 1), float(v.replace(",", ""))
        rows[month] = value
        implied[month - pd.DateOffset(years=1)] = round(value / (1 + float(yoy) / 100))
    return (pd.Series(rows, dtype=float).sort_index(),
            pd.Series(implied, dtype=float).sort_index())


def fetch(indicators: list[dict], today: pd.Timestamp, backfill: bool = False) -> dict[str, pd.Series]:
    html = http.get(STAT_URL).content.decode("cp932", errors="ignore")
    candidates = list(dict.fromkeys(re.findall(r'href="([^"]*?\d{8,}\.pdf)"', html)))
    for href in candidates[:4]:  # 先頭付近に最新の半導体・FPD・世界統計が並ぶ
        url = href if href.startswith("http") else STAT_URL + href.lstrip("./")
        doc = fitz.open(stream=http.get(url).content, filetype="pdf")
        text = "\n".join(p.get_text() for p in doc)
        if "半導体製造装置" in text and "販売高" in text and "FPD" not in text[:200]:
            actual, implied = parse_release(text)
            if actual.empty:
                continue
            out = {}
            for ind in indicators:
                have = store.load(ind["id"]).index
                fill = implied[~implied.index.isin(have) & ~implied.index.isin(actual.index)]
                out[ind["id"]] = pd.concat([actual, fill]).sort_index()
            return out
    raise ValueError("SEAJ: 半導体製造装置の販売高PDFが見つからない（ページ構成変更の可能性）")
