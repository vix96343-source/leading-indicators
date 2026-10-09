"""data/ から docs/index.html を生成する。"""
import json
from datetime import datetime
from urllib.parse import quote

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import analyze, store
from .fetch import JST, STATUS_PATH, load_config, today_jst
from .sources import stocks, trendforce

DOCS = store.ROOT / "docs"      # 公開版（GitHub Pages）
LOCAL = store.ROOT / "local"    # 全指標版（転載制限のあるデータを含む。git 管理外）
SOURCE_LABEL = {"stocks": "Yahoo Finance（関連企業）", "ctia": "中钨在线", "industry_jp": "業界統計（国交省・鉄鋼連盟・産機工・JNTO）", "esri": "内閣府", "trendforce": "TrendForce", "fred": "FRED", "yfinance": "Yahoo Finance",
                "jmtba": "日本工作機械工業会", "seaj": "日本半導体製造装置協会"}


INDUSTRY_JP_LABEL = {"housing": "国土交通省", "steel": "日本鉄鋼連盟", "jsim": "日本産業機械工業会", "inbound": "JNTO"}


def source_label(ind: dict) -> str:
    if ind["source"] == "industry_jp":
        return INDUSTRY_JP_LABEL[ind["params"]["field"].split("_")[0]]
    return SOURCE_LABEL[ind["source"]]


def source_url(ind: dict) -> str:
    p = ind["params"]
    return {
        "fred": lambda: f"https://fred.stlouisfed.org/series/{p['series']}",
        "yfinance": lambda: f"https://finance.yahoo.com/quote/{quote(p['ticker'])}",
        "jmtba": lambda: "https://www.jmtba.or.jp/statistics/",
        "ctia": lambda: "https://www.ctia.com.cn/prices/tungsten-price",
        "industry_jp": lambda: {
            "housing": "https://www.mlit.go.jp/sogoseisaku/jouhouka/sosei_jouhouka_tk4_000002.html",
            "steel": "https://www.jisf.or.jp/data/seisan/",
            "jsim": "https://www.jsim.or.jp/statistical-data/",
            "inbound": "https://www.jnto.go.jp/statistics/data/visitors-statistics/",
        }[p["field"].split("_")[0]],
        "esri": lambda: "https://www.esri.cao.go.jp/jp/stat/juchu/juchu.html",
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


def data_date(d: pd.Timestamp, freq: str) -> str:
    return d.strftime("%Y/%m" if freq == "monthly" else "%Y/%m/%d")


def row(ind: dict, today: pd.Timestamp, fetched: dict[str, str]) -> dict:
    s = store.load(ind["id"]) * ind.get("scale", 1)
    a = analyze.summarize(ind, s, today)
    kind = "daily" if ind["freq"] == "daily" else "yoy" if ind.get("yoy") else "level"
    by_label = {l: (v, u) for l, v, u in a["metrics"]}
    cols = []
    for label in COLUMNS[kind]:
        v, u = by_label.get(label, (None, ""))
        cols.append({"value": fmt(v, u, signed=True), "cls": _cls(v)})
    return {
        "id": ind["id"], "name": ind["name"], "lead": ind.get("lead", ""), "unit": ind.get("unit", ""),
        "kind": kind, "section": None,
        "value": fmt(a["latest"]),
        "date": data_date(a["latest_date"], ind["freq"]) if a["latest"] is not None else "—",
        "fetched": fetched.get(ind["source"], "—"),
        "stale": a.get("stale", False),
        "cols": cols,
        "source": source_label(ind), "source_url": source_url(ind),
        "related": ind.get("related", ""),
    }


def tf_rows(today: pd.Timestamp, fetched: dict[str, str], related: str = "") -> list[dict]:
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
        out.append({
            "id": m["id"], "name": m["item"], "lead": m["section"], "unit": "USD", "kind": "tf",
            "section": m["section"],
            "value": fmt(last), "date": data_date(last_date, "daily"), "fetched": fetched.get("trendforce", "—"),
            "stale": (today - last_date).days > 7,
            "cols": [{"value": fmt(v, "%", signed=True), "cls": _cls(v)} for v in (prev, c1m, c3m)],
            "source": "TrendForce", "source_url": m["url"], "related": related,
        })
    return out


def stock_quote(market: str, code: str, name: str) -> dict:
    sym = stocks.yahoo_symbol(market, code)
    s = store.load(stocks.series_id(sym))
    q = {"code": code, "name": name, "price": "—", "chg": "—", "chg_cls": "flat", "m1": "—", "m1_cls": "flat",
         "url": f"https://kabutan.jp/stock/?code={code}" if market == "jp" else f"https://finance.yahoo.com/quote/{code}"}
    if s.empty:
        return q
    last = float(s.iloc[-1])
    q["price"] = f"{last:,.0f}" if market == "jp" and last >= 100 else f"{last:,.2f}"
    if len(s) >= 2:
        d = (last / float(s.iloc[-2]) - 1) * 100
        q["chg"], q["chg_cls"] = f"{d:+.2f}%", _cls(d)
    base = s[s.index <= s.index[-1] - pd.Timedelta(days=30)]
    if not base.empty:
        m = (last / float(base.iloc[-1]) - 1) * 100
        q["m1"], q["m1_cls"] = f"{m:+.1f}%", _cls(m)
    return q


def basket_data(keys: set[str]) -> dict:
    baskets = stocks.load_baskets()
    return {k: {"name": baskets[k]["name"],
                "jp": [stock_quote("jp", c, n) for c, n in baskets[k].get("jp") or []],
                "us": [stock_quote("us", c, n) for c, n in baskets[k].get("us") or []]}
            for k in sorted(keys) if k in baskets}


def _cls(v):
    if v is None or pd.isna(v) or v == 0:
        return "flat"
    return "up" if v > 0 else "down"


def build(public: bool = False) -> str:
    cfg = load_config()
    today = today_jst()
    inds = [i for i in cfg["indicators"] if not (public and i.get("restricted"))]
    status = json.loads(STATUS_PATH.read_text(encoding="utf-8")) if STATUS_PATH.exists() else {}
    fetched = {k: datetime.fromisoformat(v["at"]).strftime("%m/%d %H:%M")
               for k, v in status.items() if v.get("ok") and v.get("at")}
    rows = {i["id"]: row(i, today, fetched) for i in inds}

    groups = []
    for g in cfg["groups"]:
        rs = [rows[i["id"]] for i in inds if i["group"] == g["id"]]
        if not public and cfg.get("trendforce", {}).get("group") == g["id"]:
            rs = tf_rows(today, fetched, cfg["trendforce"].get("related", "")) + rs
        if rs:
            note = g.get("public_note", g["note"]) if public else g["note"]
            groups.append({**g, "note": note, "rows": rs})

    used = {i["source"] for i in inds} | {"stocks"}
    if not public and cfg.get("trendforce"):
        used.add("trendforce")
    status_rows = [{"name": SOURCE_LABEL.get(k, k), **v, "at": v.get("at", "")[:16].replace("T", " ")}
                   for k, v in status.items() if k in used]

    env = Environment(loader=FileSystemLoader(store.ROOT / "templates"),
                      autoescape=select_autoescape(["html", "j2"]))
    html = env.get_template("index.html.j2").render(
        title=cfg["site"]["title"],
        generated_at=datetime.now(JST).strftime("%Y/%m/%d %H:%M"),
        groups=groups, columns=COLUMNS,
        baskets=basket_data({r["related"] for g in groups for r in g["rows"] if r["related"]}),
        status=status_rows, public=public,
    )
    out_dir = DOCS if public else LOCAL
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    if public:
        (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    return str(out)
