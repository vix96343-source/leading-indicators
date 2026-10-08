"""data/ から docs/index.html を生成する。"""
import json
from datetime import datetime
from urllib.parse import quote

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import analyze, charts, store
from .fetch import JST, STATUS_PATH, load_config, today_jst
from .sources import tdnet, trendforce

DOCS = store.ROOT / "docs"      # 公開版（GitHub Pages）
LOCAL = store.ROOT / "local"    # 全指標版（転載制限のあるデータを含む。git 管理外）
SOURCE_LABEL = {"trendforce": "TrendForce", "fred": "FRED", "yfinance": "Yahoo Finance",
                "jmtba": "日本工作機械工業会", "seaj": "日本半導体製造装置協会", "tdnet": "TDnet"}
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


def fmt(v, unit="", signed=False):
    if v is None or pd.isna(v):
        return "—"
    if unit in ("%", "pt"):
        return f"{v:+.1f}{unit}" if signed else f"{v:.1f}{unit}"
    return charts.fmt_num(v)


def card(ind: dict, today: pd.Timestamp) -> dict:
    s = store.load(ind["id"]) * ind.get("scale", 1)
    a = analyze.summarize(ind, s, today)
    yoy_chart = a.get("chart_kind") == "yoy"
    chart = a.get("chart")
    chart_unit = "%" if yoy_chart else ""
    recent = []
    for d, v in a.get("recent", []):
        y = a.get("recent_yoy", {}).get(d)
        recent.append({"date": d.strftime("%Y-%m" if ind["freq"] == "monthly" else "%Y-%m-%d"),
                       "value": fmt(v), "yoy": fmt(y, "%", signed=True) if y is not None else ""})
    return {
        "id": ind["id"], "name": ind["name"], "lead": ind.get("lead", ""), "unit": ind.get("unit", ""),
        "freq": "日次" if ind["freq"] == "daily" else "月次",
        "latest": fmt(a["latest"]),
        "latest_date": a["latest_date"].strftime("%Y-%m" if ind["freq"] == "monthly" else "%Y-%m-%d") if a["latest"] is not None else "",
        "stale": a.get("stale", False),
        "n": a["n"],
        "direction": a["direction"], "arrow": ARROW[a["direction"]], "direction_label": (YOY_DIRECTION_LABEL if ind.get("yoy") else DIRECTION_LABEL)[a["direction"]],
        "tone": a["tone"], "good": ind.get("good", "neutral"),
        "metrics": [{"label": l, "value": fmt(v, u, signed=True), "sign": "pos" if (v or 0) > 0 else "neg" if (v or 0) < 0 else ""}
                    for l, v, u in a["metrics"]],
        "has_metrics": any(v is not None for _, v, _ in a["metrics"]),
        "range_pos": a.get("range_pos"),
        "chart_label": "前年比 %（5年）" if yoy_chart else ("過去1年" if ind["freq"] == "daily" else "過去5年"),
        "spark": charts.line(chart, 240, 48, zero_line=yoy_chart, tone=a["tone"]),
        "big": charts.line(chart, 400, 170, zero_line=yoy_chart, axes=True, unit=chart_unit, tone=a["tone"]),
        "recent": recent,
        "show_yoy_col": ind["freq"] == "monthly" and ind.get("yoy"),
        "source": SOURCE_LABEL[ind["source"]], "source_url": source_url(ind),
        "accumulating": ind["source"] in ("trendforce",) and a["n"] < 60,
    }


def build(public: bool = False) -> str:
    cfg = load_config()
    today = today_jst()
    inds = [i for i in cfg["indicators"] if not (public and i.get("restricted"))]
    cards = {i["id"]: card(i, today) for i in inds}

    groups = []
    for g in cfg["groups"]:
        cs = [cards[i["id"]] for i in inds if i["group"] == g["id"]]
        if cs:
            note = g.get("public_note", g["note"]) if public else g["note"]
            groups.append({**g, "note": note, "cards": cs})

    tally = {"good": 0, "bad": 0, "other": 0}
    for c in cards.values():
        tally[c["tone"] if c["tone"] in ("good", "bad") else "other"] += 1
    movers = sorted((c for c in cards.values() if c["tone"] in ("good", "bad")),
                    key=lambda c: (c["tone"] != "bad", c["name"]))

    comp_cfg = cfg.get("companies", {})
    disc = tdnet.load()
    watch_names = {w["code"]: w["name"] for w in comp_cfg.get("watchlist", [])}
    disclosures = disc.to_dict("records")

    status = json.loads(STATUS_PATH.read_text(encoding="utf-8")) if STATUS_PATH.exists() else {}
    used = {i["source"] for i in inds} | {"tdnet"}
    status_rows = [{"name": SOURCE_LABEL.get(k, k), **v, "at": v.get("at", "")[:16].replace("T", " ")}
                   for k, v in status.items() if k in used]

    env = Environment(loader=FileSystemLoader(store.ROOT / "templates"),
                      autoescape=select_autoescape(["html", "j2"]))
    html = env.get_template("index.html.j2").render(
        title=cfg["site"]["title"],
        generated_at=datetime.now(JST).strftime("%Y-%m-%d %H:%M"),
        groups=groups, tally=tally, movers=movers,
        disclosures=disclosures, watch_names=watch_names,
        status=status_rows, public=public,
    )
    out_dir = DOCS if public else LOCAL
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    if public:
        (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    return str(out)
