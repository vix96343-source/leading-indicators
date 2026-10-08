"""data/ から docs/index.html を生成する。"""
import json
from datetime import datetime
from urllib.parse import quote

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import analyze, store
from .fetch import JST, STATUS_PATH, load_config, today_jst
from .sources import trendforce

DOCS = store.ROOT / "docs"      # 公開版（GitHub Pages）
LOCAL = store.ROOT / "local"    # 全指標版（転載制限のあるデータを含む。git 管理外）
SOURCE_LABEL = {"esri": "内閣府", "trendforce": "TrendForce", "fred": "FRED", "yfinance": "Yahoo Finance",
                "jmtba": "日本工作機械工業会", "seaj": "日本半導体製造装置協会"}
ARROW = {"up": "↑", "down": "↓", "flat": "→", "none": "・"}
DIRECTION_LABEL = {"up": "上昇", "down": "下落", "flat": "横ばい", "none": "判定不可"}
YOY_DIRECTION_LABEL = {"up": "加速", "down": "減速", "flat": "横ばい", "none": "判定不可"}


def source_url(ind: dict) -> str:
    p = ind["params"]
    return {
        "fred": lambda: f"https://fred.stlouisfed.org/series/{p['series']}",
        "yfinance": lambda: f"https://finance.yahoo.com/quote/{quote(p['ticker'])}",
        "jmtba": lambda: "https://www.jmtba.or.jp/statistics/",
        "esri": lambda: ("https://www.esri.cao.go.jp/jp/stat/di/di.html" if p["field"] == "ci_leading"
                         else "https://www.esri.cao.go.jp/jp/stat/juchu/juchu.html"),
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
    "tf": ("前回比", "1か月", "3か月"),
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
        "kind": kind, "section": None,
        "value": fmt(a["latest"]),
        "date": a["latest_date"].strftime("%y/%m" if ind["freq"] == "monthly" else "%m/%d") if a["latest"] is not None else "—",
        "stale": a.get("stale", False),
        "cols": cols,
        "judge": "—" if a["direction"] == "none" else f'{ARROW[a["direction"]]}{labels[a["direction"]]}',
        "judge_cls": TONE_CLASS.get(a["tone"], "flat"),
        "source": SOURCE_LABEL[ind["source"]], "source_url": source_url(ind),
    }


def tf_rows(today: pd.Timestamp) -> list[dict]:
    """TrendForce の全品目。前回比は TrendForce 表示の値、1か月・3か月は蓄積した履歴から計算。"""
    out = []
    for m in trendforce.load_meta():
        s = store.load(m["id"])
        if s.empty:
            continue
        last_date, last = s.index[-1], float(s.iloc[-1])
        chg_s = store.load(m["id"] + "__chg")
        prev = chg_s.iloc[-1] if not chg_s.empty and chg_s.index[-1] == last_date else None

        def since(days):
            base = s[s.index <= last_date - pd.Timedelta(days=days)]
            return None if base.empty else (last / float(base.iloc[-1]) - 1) * 100

        c1m, c3m = since(30), since(91)
        basis, thr = (c1m, 3.0) if c1m is not None else (prev, 0.5)
        direction = "none" if basis is None else "up" if basis >= thr else "down" if basis <= -thr else "flat"
        out.append({
            "id": m["id"], "name": m["item"], "lead": m["section"], "unit": "USD", "kind": "tf",
            "section": m["section"],
            "value": fmt(last), "date": last_date.strftime("%m/%d"),
            "stale": (today - last_date).days > 7,
            "cols": [{"value": fmt(v, "%", signed=True), "cls": _cls(v)} for v in (prev, c1m, c3m)],
            "judge": "—" if direction == "none" else f"{ARROW[direction]}{DIRECTION_LABEL[direction]}",
            "judge_cls": {"up": "up", "down": "down"}.get(direction, "flat"),
            "source": "TrendForce", "source_url": m["url"],
        })
    return out


def _cls(v):
    if v is None or pd.isna(v) or v == 0:
        return "flat"
    return "up" if v > 0 else "down"


def build(public: bool = False) -> str:
    cfg = load_config()
    today = today_jst()
    inds = [i for i in cfg["indicators"] if not (public and i.get("restricted"))]
    rows = {i["id"]: row(i, today) for i in inds}

    groups = []
    for g in cfg["groups"]:
        rs = [rows[i["id"]] for i in inds if i["group"] == g["id"]]
        if not public and cfg.get("trendforce", {}).get("group") == g["id"]:
            rs = tf_rows(today) + rs
        if rs:
            note = g.get("public_note", g["note"]) if public else g["note"]
            groups.append({**g, "note": note, "rows": rs})

    tally = {"up": 0, "down": 0, "flat": 0}
    for r in (r for g in groups for r in g["rows"]):
        tally[r["judge_cls"]] += 1


    status = json.loads(STATUS_PATH.read_text(encoding="utf-8")) if STATUS_PATH.exists() else {}
    used = {i["source"] for i in inds}
    if not public and cfg.get("trendforce"):
        used.add("trendforce")
    status_rows = [{"name": SOURCE_LABEL.get(k, k), **v, "at": v.get("at", "")[:16].replace("T", " ")}
                   for k, v in status.items() if k in used]

    env = Environment(loader=FileSystemLoader(store.ROOT / "templates"),
                      autoescape=select_autoescape(["html", "j2"]))
    html = env.get_template("index.html.j2").render(
        title=cfg["site"]["title"],
        generated_at=datetime.now(JST).strftime("%Y-%m-%d %H:%M"),
        groups=groups, tally=tally, columns=COLUMNS,
        status=status_rows, public=public,
    )
    out_dir = DOCS if public else LOCAL
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    if public:
        (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    return str(out)
