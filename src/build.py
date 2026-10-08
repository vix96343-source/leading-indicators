"""data/ から docs/index.html を生成する。"""
import json
from datetime import datetime
from urllib.parse import quote

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import analyze, store
from .fetch import JST, STATUS_PATH, load_config, today_jst
from .sources import tdnet, trendforce

DOCS = store.ROOT / "docs"      # 公開版（GitHub Pages）
LOCAL = store.ROOT / "local"    # 全指標版（転載制限のあるデータを含む。git 管理外）
SOURCE_LABEL = {"trendforce": "TrendForce", "fred": "FRED", "yfinance": "Yahoo Finance",
                "jmtba": "日本工作機械工業会", "seaj": "日本半導体製造装置協会", "tdnet": "TDnet",
                "stocks": "Yahoo Finance（注目銘柄）"}
ARROW = {"up": "↑", "down": "↓", "flat": "→", "none": "・"}
DIRECTION_LABEL = {"up": "上昇", "down": "下落", "flat": "横ばい", "none": "判定不可"}
YOY_DIRECTION_LABEL = {"up": "加速", "down": "減速", "flat": "横ばい", "none": "判定不可"}


def source_url(ind: dict) -> str:
    p = ind["params"]
    return {
        "trendforce": lambda: trendforce.BASE + trendforce.PAGES[p["page"]],
        "fred": lambda: f"https://fred.stlouisfed.org/series/{p['series']}",
        "yfinance": lambda: f"https://finance.yahoo.com/quote/{quote(p['ticker'])}",
        "jmtba": lambda: "https://www.jmtba.or.jp/statistics/",
        "seaj": lambda: "https://www.seaj.or.jp/statistics/",
    }[ind["source"]]()


def fmt_num(v: float) -> str:
    a = abs(v)
    if a >= 1000:
        return f"{v:,.0f}"
    if a >= 100:
        return f"{v:,.1f}"
    if a >= 1:
        return f"{v:,.2f}"
    return f"{v:,.3f}"


def fmt(v, unit="", signed=False):
    if v is None or pd.isna(v):
        return "—"
    if unit in ("%", "pt"):
        return f"{v:+.1f}{unit}" if signed else f"{v:.1f}{unit}"
    return fmt_num(v)


# 表の変化率 3 列に何を出すか（指標の種類ごと）
COLUMNS = {
    "daily": ("1か月", "3か月", "1年"),
    "yoy": ("前年比", "加速", "前月比"),
    "level": ("前月比", "3か月", "前年比"),
}
TONE_CLASS = {"good": "up", "bad": "down", "neutral": "flat"}


def row(ind: dict, today: pd.Timestamp) -> dict:
    s = store.load(ind["id"]) * ind.get("scale", 1)
    a = analyze.summarize(ind, s, today)
    kind = "daily" if ind["freq"] == "daily" else "yoy" if ind.get("yoy") else "level"
    by_label = {l: (v, u) for l, v, u in a["metrics"]}
    cols = []
    for label in COLUMNS[kind]:
        v, u = by_label.get(label, (None, ""))
        cols.append({"value": fmt(v, u, signed=True), "cls": _cls(v)})
    labels = YOY_DIRECTION_LABEL if kind == "yoy" else DIRECTION_LABEL
    return {
        "id": ind["id"], "name": ind["name"], "lead": ind.get("lead", ""), "unit": ind.get("unit", ""),
        "kind": kind,
        "value": fmt(a["latest"]),
        "date": a["latest_date"].strftime("%y/%m" if ind["freq"] == "monthly" else "%m/%d") if a["latest"] is not None else "—",
        "stale": a.get("stale", False),
        "cols": cols,
        "judge": "—" if a["direction"] == "none" else f'{ARROW[a["direction"]]}{labels[a["direction"]]}',
        "judge_cls": TONE_CLASS.get(a["tone"], "flat"),
        "source": SOURCE_LABEL[ind["source"]], "source_url": source_url(ind),
    }


def _cls(v):
    if v is None or pd.isna(v) or v == 0:
        return "flat"
    return "up" if v > 0 else "down"


def stock_rows(cfg: dict, today: pd.Timestamp) -> tuple[list[dict], str]:
    groups, dates = [], []
    for g in cfg["stocks"]["groups"]:
        rows = []
        for it in g["items"]:
            s = store.load(f"stock_{it['code']}")
            price = chg = pct = None
            if len(s) >= 1:
                price = float(s.iloc[-1])
                dates.append(s.index[-1])
            if len(s) >= 2:
                chg = price - float(s.iloc[-2])
                pct = chg / float(s.iloc[-2]) * 100
            q, a = it.get("q_yoy"), it.get("accel")
            rows.append({
                "code": it["code"], "name": it["name"],
                "price": "—" if price is None else (f"{price:,.0f}" if price >= 100 else f"{price:,.1f}"),
                "stale": len(s) == 0 or (today - s.index[-1]).days > 5,
                "chg": "—" if chg is None else f"{chg:+,.0f}" if abs(price) >= 100 else f"{chg:+,.1f}",
                "pct": "—" if pct is None else f"{pct:+.2f}%",
                "cls": _cls(chg),
                "q_yoy": "—" if q is None else f"{q:+.1f}%", "q_cls": _cls(q),
                "accel": "—" if a is None else f"{a:+.1f}", "a_cls": _cls(a),
            })
        groups.append({"name": g["name"], "rows": rows})
    price_date = max(dates).strftime("%Y-%m-%d") if dates else "—"
    return groups, price_date


def build(public: bool = False) -> str:
    cfg = load_config()
    today = today_jst()
    inds = [i for i in cfg["indicators"] if not (public and i.get("restricted"))]
    rows = {i["id"]: row(i, today) for i in inds}

    groups = []
    for g in cfg["groups"]:
        rs = [rows[i["id"]] for i in inds if i["group"] == g["id"]]
        if rs:
            note = g.get("public_note", g["note"]) if public else g["note"]
            groups.append({**g, "note": note, "rows": rs})

    tally = {"up": 0, "down": 0, "flat": 0}
    for r in rows.values():
        tally[r["judge_cls"]] += 1

    comp_cfg = cfg.get("companies", {})
    disc = tdnet.load()
    watch_names = {w["code"]: w["name"] for w in comp_cfg.get("watchlist", [])}
    disclosures = disc.to_dict("records")

    status = json.loads(STATUS_PATH.read_text(encoding="utf-8")) if STATUS_PATH.exists() else {}
    used = {i["source"] for i in inds} | {"tdnet", "stocks"}
    status_rows = [{"name": SOURCE_LABEL.get(k, k), **v, "at": v.get("at", "")[:16].replace("T", " ")}
                   for k, v in status.items() if k in used]

    env = Environment(loader=FileSystemLoader(store.ROOT / "templates"),
                      autoescape=select_autoescape(["html", "j2"]))
    html = env.get_template("index.html.j2").render(
        title=cfg["site"]["title"],
        generated_at=datetime.now(JST).strftime("%Y-%m-%d %H:%M"),
        groups=groups, tally=tally, columns=COLUMNS,
        disclosures=disclosures, watch_names=watch_names,
        status=status_rows, public=public,
    )
    out_dir = DOCS if public else LOCAL
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    if cfg.get("stocks"):
        groups_s, price_date = stock_rows(cfg, today)
        (out_dir / "stocks.html").write_text(env.get_template("stocks.html.j2").render(
            groups=groups_s, price_date=price_date, as_of=cfg["stocks"].get("as_of", "")), encoding="utf-8")
    if public:
        (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    return str(out)
