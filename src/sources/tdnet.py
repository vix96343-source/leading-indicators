"""TDnet 適時開示一覧から、月次・受注などの先行開示を拾う。TDnet の一覧は直近約1か月分しか残らない。"""
import re
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from .. import http, store

BASE = "https://www.release.tdnet.info/inbs/"
CSV_PATH = store.ROOT / "data" / "company" / "disclosures.csv"
COLUMNS = ["date", "time", "code", "company", "title", "url", "match"]


def parse_list_page(html: str, date: str, page: int = 1) -> tuple[list[dict], bool]:
    """一覧ページ1枚分 → (開示のリスト, 次ページがあるか)。"""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="main-list-table")
    items = []
    if table is None:
        return items, False
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        t = tds[0].get_text(strip=True)
        if not re.fullmatch(r"\d{1,2}:\d{2}", t):
            continue
        a = tds[3].find("a", href=re.compile(r"\.pdf", re.I))
        items.append({
            "date": date,
            "time": t,
            "code": tds[1].get_text(strip=True)[:4],
            "company": tds[2].get_text(strip=True),
            "title": tds[3].get_text(strip=True),
            "url": BASE + a["href"].lstrip("/") if a else "",
        })
    # 「次へ」は <div onClick="pager('I_list_002_...')"> で、<a> ではない
    has_next = f"I_list_{page + 1:03d}_" in html
    return items, has_next and bool(items)


def fetch_day(day: pd.Timestamp) -> list[dict]:
    date = day.strftime("%Y%m%d")
    items, page = [], 1
    while True:
        try:
            r = http.get(f"{BASE}I_list_{page:03d}_{date}.html")
        except Exception:
            break  # 休日・範囲外は 404
        r.encoding = "utf-8"
        got, has_next = parse_list_page(r.text, day.strftime("%Y-%m-%d"), page)
        items += got
        if not has_next:
            break
        page += 1
    return items


def select(items: list[dict], cfg: dict) -> list[dict]:
    watch = {w["code"] for w in cfg.get("watchlist", [])}
    kws, ukws = cfg.get("keywords", []), cfg.get("universe_keywords", [])
    picked = []
    for it in items:
        if it["code"] in watch and any(k in it["title"] for k in kws):
            picked.append({**it, "match": "watchlist"})
        elif any(k in it["title"] for k in ukws):
            picked.append({**it, "match": "keyword"})
    return picked


def load() -> pd.DataFrame:
    if not CSV_PATH.exists():
        return pd.DataFrame(columns=COLUMNS)
    return pd.read_csv(CSV_PATH, dtype=str).fillna("")


def update(cfg: dict, today: pd.Timestamp, backfill: bool = False) -> int:
    days = 30 if backfill else cfg.get("lookback_days", 3)
    new = []
    for d in pd.bdate_range(end=today, periods=days):
        new += select(fetch_day(d), cfg)
    old = load()
    df = pd.concat([old, pd.DataFrame(new, columns=COLUMNS)], ignore_index=True)
    df = df.drop_duplicates(subset=["date", "code", "title"], keep="last")
    cutoff = (today - pd.Timedelta(days=cfg.get("keep_days", 120))).strftime("%Y-%m-%d")
    df = df[df["date"] >= cutoff].sort_values(["date", "time"], ascending=False)
    Path(CSV_PATH).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(CSV_PATH, index=False)
    return len(df) - len(old)
