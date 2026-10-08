"""TrendForce の DRAM・NAND 価格表（ログイン不要で見える全品目）。

ページ上の当日値だけが取れるので、毎営業日取得して履歴を蓄積する。
TrendForce の規約は個人・非商用の利用のみ許可し、許可なく公開・配布することを禁じている。
そのため公開版（--public）では取得も表示もしない。
"""
import json
import re

import pandas as pd
from bs4 import BeautifulSoup

from .. import http, store

BASE = "https://www.trendforce.com/price/"
PAGES = {"dram": "dram/dram_spot", "flash": "flash/flash_spot"}
# ページ内の数値付きの表（見出しが Item / Brand のもの）に、上から順に付ける名前
SECTIONS = {
    "dram": ["DRAM スポット", "DRAM 契約", "DRAMモジュール スポット", "GDDR スポット"],
    "flash": ["NAND スポット", "NAND 契約", "NANDウェハ スポット", "メモリカード スポット",
              "PC向けSSD 契約", "SSD 店頭"],
}
AVG_COLS = ("Session Average", "Average")
CHG_COLS = ("Session Change", "Average Change", "Change")
META_PATH = store.ROOT / "data" / "trendforce_items.json"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _num(s: str):
    m = re.search(r"-?[\d,]+(?:\.\d+)?", s)
    return float(m.group(0).replace(",", "")) if m else None


def _chg(s: str):
    """「▲ 0.29 %」「▼ -2.45 %」「— 0.00 %」→ 0.29 / -2.45 / 0.0"""
    v = _num(s)
    if v is None:
        return None
    return -abs(v) if "▼" in s else v


def slug(page: str, item: str) -> str:
    return "tf_" + re.sub(r"[^a-z0-9]+", "_", f"{page}_{item}".lower()).strip("_")


def parse_page(html: str, page: str) -> list[dict]:
    """価格表の全品目 → [{"id", "section", "item", "avg", "chg"}, ...]（ページ上の順）。"""
    rows, n_table = [], 0
    names = SECTIONS.get(page, [])
    for table in BeautifulSoup(html, "html.parser").find_all("table"):
        trs = table.find_all("tr")
        if not trs:
            continue
        header = [_norm(c.get_text(" ")) for c in trs[0].find_all(["th", "td"])]
        if not header or header[0] not in ("Item", "Brand"):
            continue  # 品目名だけの表（契約価格の会員限定部分）は数値が無い
        section = names[n_table] if n_table < len(names) else f"{page} 表{n_table + 1}"
        n_table += 1
        avg_i = next((header.index(c) for c in AVG_COLS if c in header), None)
        chg_i = next((header.index(c) for c in CHG_COLS if c in header), None)
        if avg_i is None:
            continue
        for tr in trs[1:]:
            cells = [_norm(c.get_text(" ")) for c in tr.find_all(["th", "td"])]
            if len(cells) <= avg_i:
                continue  # 「〜 updated on 9/30」のような注記行
            if header[0] == "Brand":  # SSD 店頭価格はブランド・シリーズ・容量で1品目
                item = " ".join(cells[i] for i, h in enumerate(header) if h in ("Brand", "Series", "Capacity"))
            else:
                item = cells[0]
            avg = _num(cells[avg_i])
            if not item or avg is None:
                continue
            rows.append({"id": slug(page, item), "section": section, "item": item, "avg": avg,
                         "chg": _chg(cells[chg_i]) if chg_i is not None and chg_i < len(cells) else None})
    return rows


def fetch_all(today: pd.Timestamp) -> dict[str, pd.Series]:
    """全品目を取得し、平均価格を <id>、TrendForce 表示の変化率を <id>__chg として返す。品目一覧も保存する。"""
    out, meta = {}, []
    for page, path in PAGES.items():
        rows = parse_page(http.get(BASE + path).text, page)
        if not rows:
            raise ValueError(f"TrendForce: {path} に価格表が見つからない（ページ構成変更の可能性）")
        for r in rows:
            out[r["id"]] = pd.Series({today: r["avg"]})
            if r["chg"] is not None:
                out[r["id"] + "__chg"] = pd.Series({today: r["chg"]})
            meta.append({"id": r["id"], "page": page, "section": r["section"], "item": r["item"],
                         "url": BASE + path})
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def load_meta() -> list[dict]:
    if not META_PATH.exists():
        return []
    return json.loads(META_PATH.read_text(encoding="utf-8"))
