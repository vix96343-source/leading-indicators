"""国内の業界統計（公開ファイルから取得、API キー不要）。

- 住宅着工（国土交通省 建築着工統計）: jyuu_ken.xls に 1965 年以降の月次。総計・持家・貸家（戸数）。
- 粗鋼生産（日本鉄鋼連盟）: seisan_tuki.xls は当月分だけ。前年同月比から前年同月の値を逆算して初回から前年比を出す。
- 産業機械受注（日本産業機械工業会）: 毎月の PDF 本文「本月の受注高は6,313億7,500万円」から総額・内需・外需。
- 訪日外客数（JNTO）: 国籍/月別の xlsx（年ごとのシート）。総数と中国。
"""
import io
import re
import unicodedata

import pandas as pd
import pymupdf

from .. import http, store

MLIT_URL = "https://www.mlit.go.jp/sogoseisaku/jouhouka/content/jyuu_ken.xls"
# jyuu シート: 1列目=総計戸数, 5列目=持家戸数, 9列目=貸家戸数
MLIT_COLS = {"housing_total": 1, "housing_owner": 5, "housing_rental": 9}
ERA = {"S": 1925, "H": 1988, "R": 2018}

JISF_URL = "https://www.jisf.or.jp/data/seisan/documents/seisan_tuki.xls"

JSIM_INDEX = "https://www.jsim.or.jp/statistical-data/"
JSIM_BASE = "https://www.jsim.or.jp"

JNTO_INDEX = "https://www.jnto.go.jp/statistics/data/visitors-statistics/"
JNTO_BASE = "https://www.jnto.go.jp"
JNTO_ROWS = {"inbound_total": "総数", "inbound_china": "中国"}


def _nfkc(s) -> str:
    return unicodedata.normalize("NFKC", str(s)).strip()


def parse_mlit(xls: bytes) -> dict[str, pd.Series]:
    df = pd.read_excel(io.BytesIO(xls), sheet_name="jyuu", header=None)
    vals = {k: {} for k in MLIT_COLS}
    year = None
    for _, row in df.iterrows():
        label = _nfkc(row[0])
        m = re.match(r"([SHR])\s*(\d+)\s*年\s*(\d+)\s*月", label)  # 「R8年 8月」
        if m:
            year, month = ERA[m.group(1)] + int(m.group(2)), int(m.group(3))
        elif year is not None and re.fullmatch(r"\d{1,2}", label):  # 年の無い行は「2」「3」…
            month = int(label)
        else:
            continue  # 年度計・期間計・注記の行
        for key, col in MLIT_COLS.items():
            v = pd.to_numeric(row[col], errors="coerce")
            if pd.notna(v):
                vals[key][pd.Timestamp(year, month, 1)] = float(v)
    return {k: pd.Series(v, dtype=float).sort_index() for k, v in vals.items() if v}


def parse_jisf(xls: bytes) -> tuple[pd.Timestamp, float, float]:
    """(対象月, 粗鋼生産 千トン, 前年同月比 %) を返す。"""
    df = pd.read_excel(io.BytesIO(xls), sheet_name=0, header=None)
    month = pd.Timestamp(df.iloc[1, 2]).normalize().replace(day=1)
    row = df[df[0].map(lambda x: _nfkc(x).replace(" ", "") == "粗鋼")].iloc[0]
    return month, float(row[1]), float(row[3]) - 100  # 前年同月比は「100.4」形式


def _oku(s: str) -> float:
    """「6,313億7,500万円」→ 6313.75、「1兆36億200万円」→ 10036.02（億円）。"""
    m = re.match(r"(?:([\d,]+)兆)?(?:([\d,]+)億)?(?:([\d,]+)万)?", s)
    n = lambda g: float(g.replace(",", "")) if g else 0.0
    return n(m.group(1)) * 10000 + n(m.group(2)) + n(m.group(3)) / 10000


def parse_jsim(text: str) -> tuple[pd.Timestamp, dict[str, float]]:
    t = re.sub(r"\s+", "", _nfkc(text))
    m = re.search(r"(\d{4})年(\d{1,2})月産業機械受注状況", t)
    if not m:
        raise ValueError("産業機械受注: 対象月が読めない")
    month = pd.Timestamp(int(m.group(1)), int(m.group(2)), 1)
    out = {}
    for key, pat in (("jsim_total", r"本月の受注高は、?((?:[\d,]+兆)?(?:[\d,]+億)?(?:[\d,]+万)?)円"),
                     ("jsim_domestic", r"内需は、?((?:[\d,]+兆)?(?:[\d,]+億)?(?:[\d,]+万)?)円"),
                     ("jsim_foreign", r"外需は、?((?:[\d,]+兆)?(?:[\d,]+億)?(?:[\d,]+万)?)円")):
        v = re.search(pat, t)
        if v:
            out[key] = _oku(v.group(1))
    if "jsim_total" not in out:
        raise ValueError("産業機械受注: 受注高が読めない")
    return month, out


def parse_jnto(xlsx: bytes) -> dict[str, pd.Series]:
    vals = {k: {} for k in JNTO_ROWS}
    for sheet, df in pd.read_excel(io.BytesIO(xlsx), sheet_name=None, header=None).items():
        if not re.fullmatch(r"\d{4}", str(sheet)):
            continue
        year = int(sheet)
        head = next(i for i in range(len(df)) if any(_nfkc(x) == "1月" for x in df.iloc[i]))
        month_cols = {c: int(_nfkc(df.iloc[head, c])[:-1]) for c in df.columns
                      if re.fullmatch(r"\d{1,2}月", _nfkc(df.iloc[head, c]))}
        for key, label in JNTO_ROWS.items():
            rows = df[df[0].map(_nfkc) == label]
            if rows.empty:
                continue
            row = rows.iloc[0]
            for c, mon in month_cols.items():
                v = pd.to_numeric(row[c], errors="coerce")
                if pd.notna(v) and v > 0:
                    vals[key][pd.Timestamp(year, mon, 1)] = float(v)
    return {k: pd.Series(v, dtype=float).sort_index() for k, v in vals.items() if v}


def fetch(indicators: list[dict], today: pd.Timestamp, backfill: bool = False) -> dict[str, pd.Series]:
    fields = {ind["params"]["field"]: ind["id"] for ind in indicators}
    out, errors = {}, []

    def run(name, fn):
        try:
            fn()
        except Exception as e:  # 1統計の失敗で他を止めない
            errors.append(f"{name}: {type(e).__name__}: {e}")

    def mlit():
        for key, s in parse_mlit(http.get(MLIT_URL).content).items():
            if key in fields:
                out[fields[key]] = s

    def jisf():
        if "steel_crude" not in fields:
            return
        month, v, yoy = parse_jisf(http.get(JISF_URL).content)
        s = pd.Series({month: v})
        prev = month - pd.DateOffset(years=1)
        if prev not in store.load(fields["steel_crude"]).index:  # 前年同月を前年比から逆算（実値があれば上書きしない）
            s[prev] = round(v / (1 + yoy / 100), 1)
        out[fields["steel_crude"]] = s.sort_index()

    def jsim():
        want = [k for k in ("jsim_total", "jsim_domestic", "jsim_foreign") if k in fields]
        if not want:
            return
        html = http.get(JSIM_INDEX).content.decode("utf-8", "ignore")
        pdfs = sorted(set(re.findall(r'href="\.{0,2}(/pdf/statistical-data/a-1-54-00-00-00-(\d{6})\.pdf)"', html)),
                      key=lambda p: p[1])
        vals = {k: {} for k in want}
        for path, _ym in (pdfs if backfill else pdfs[-2:]):
            doc = pymupdf.open(stream=http.get(JSIM_BASE + path).content, filetype="pdf")
            month, got = parse_jsim(doc[0].get_text())
            for k in want:
                if k in got:
                    vals[k][month] = got[k]
        for k in want:
            if vals[k]:
                out[fields[k]] = pd.Series(vals[k], dtype=float).sort_index()

    def jnto():
        if not set(JNTO_ROWS) & fields.keys():
            return
        html = http.get(JNTO_INDEX).content.decode("utf-8", "ignore")
        m = re.search(r'href="([^"]+\.xlsx)"[^>]*>\s*国籍/月別\s*訪日外客数', html)
        if not m:
            raise ValueError("国籍/月別 訪日外客数の xlsx が見つからない")
        for key, s in parse_jnto(http.get(JNTO_BASE + m.group(1)).content).items():
            if key in fields:
                out[fields[key]] = s

    for name, fn in (("住宅着工", mlit), ("粗鋼", jisf), ("産業機械", jsim), ("訪日客", jnto)):
        run(name, fn)
    if errors:
        print("  [業界統計 警告] " + " / ".join(errors))
    if not out:
        raise ValueError("業界統計: すべて失敗 " + " / ".join(errors))
    return out
