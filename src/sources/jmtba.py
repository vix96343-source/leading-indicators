"""日本工作機械工業会（JMTBA）の受注統計。

- 確報 PDF (kakuhouYYMM.pdf): 総額・内需・外需・中国・内需の電気精密。毎月下旬、2009年から全月公開。
- 速報 PDF (sokuhouYYMM.pdf): 総額・内需・外需のみ。確報より約3週早い。確報が出ていない月だけ使う。
"""
import re

import pymupdf as fitz
import pandas as pd

from .. import http, store

STAT_URL = "https://www.jmtba.or.jp/statistics/"
PDF_RE = re.compile(r"https://www\.jmtba\.or\.jp/wjmtbap/wp-content/uploads/\d{4}/\d{2}/(kakuhou|sokuhou)(\d{2})(\d{2})\.pdf")
NUM = r"([\d,]+)"
BACKFILL_FROM = 2015


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _first(pattern: str, text: str):
    m = re.search(pattern, text)
    return _num(m.group(1)) if m else None


def parse_kakuhou(pages: list[str]) -> dict[str, float]:
    """確報 PDF の各ページのテキストから主要項目を取り出す。見つからない項目は含めない。"""
    p0 = pages[0]
    p1 = pages[1] if len(pages) > 1 else ""
    vals = {
        "domestic": _first(r"1-11[．.]\s*\n\s*" + NUM, p0),
        "total": _first(r"1-12[．.]\s*\n\s*" + NUM, p0),
        "foreign": _first(r"\n\s*12[．.]\s*\n\s*" + NUM, p0),
        "elec_precision": _first(r"5-6[．.][\s電気・精密計]*?\n\s*" + NUM, p0),
        "china": _first(r"中\s*国\s*\n\s*" + NUM, p1),  # 「中\n国」と「中　　　国」の両方の版がある
    }
    vals = {k: v for k, v in vals.items() if v is not None}
    t, d, f = vals.get("total"), vals.get("domestic"), vals.get("foreign")
    if t is not None and d is not None and f is not None and abs(t - d - f) > 5:
        raise ValueError(f"JMTBA確報: 総額{t} ≠ 内需{d}+外需{f}（読み取り位置ずれ）")
    return vals


def parse_sokuhou(text: str) -> tuple[pd.Timestamp, dict[str, float]]:
    m = re.search(r"(\d{4})年(\d{1,2})月分", text)
    if not m:
        raise ValueError("JMTBA速報: 対象月が読めない")
    month = pd.Timestamp(int(m.group(1)), int(m.group(2)), 1)
    # 「26/8月 前月比 前年同月比 2026年累計 前年同期比」の後に 総額, …, うち内需, …, うち外需 の順で並ぶ
    total = _first(r"前年同期比\s*\n\s*" + NUM, text)
    domestic = _first(r"うち内需\s*\n\s*" + NUM, text)
    foreign = _first(r"うち外需\s*\n\s*" + NUM, text)
    vals = {"total": total, "domestic": domestic, "foreign": foreign}
    if None in vals.values():
        raise ValueError(f"JMTBA速報: 読み取り失敗 {vals}")
    if abs(total - domestic - foreign) > 5:
        raise ValueError(f"JMTBA速報: 総額{total} ≠ 内需{domestic}+外需{foreign}")
    return month, vals


def _pdf_pages(url: str) -> list[str]:
    doc = fitz.open(stream=http.get(url).content, filetype="pdf")
    return [p.get_text() for p in doc]


def list_pdfs(html: str) -> dict[str, dict[pd.Timestamp, str]]:
    found: dict[str, dict[pd.Timestamp, str]] = {"kakuhou": {}, "sokuhou": {}}
    for m in PDF_RE.finditer(html):
        kind, yy, mm = m.group(1), int(m.group(2)), int(m.group(3))
        found[kind][pd.Timestamp(2000 + yy, mm, 1)] = m.group(0)
    return found


def fetch(indicators: list[dict], today: pd.Timestamp, backfill: bool = False) -> dict[str, pd.Series]:
    pdfs = list_pdfs(http.get(STAT_URL).text)
    field_to_id = {ind["params"]["field"]: ind["id"] for ind in indicators}
    rows: dict[pd.Timestamp, dict[str, float]] = {}

    # 確報: backfill 時は全期間、通常時はまだ持っていない月（と念のため直近2か月）だけ取る
    if backfill:
        targets = [m for m in pdfs["kakuhou"] if m.year >= BACKFILL_FROM]
    else:
        have = store.load(field_to_id.get("total", next(iter(field_to_id.values())))).index
        latest = sorted(pdfs["kakuhou"])[-2:]
        targets = [m for m in pdfs["kakuhou"] if m.year >= BACKFILL_FROM and m not in have] + latest
    errors = []
    for month in sorted(set(targets)):
        try:
            rows[month] = parse_kakuhou(_pdf_pages(pdfs["kakuhou"][month]))
        except Exception as e:  # 1か月分の失敗で全体を止めない
            errors.append(f"{month:%Y-%m}: {e}")

    # 速報: 確報より新しい月のときだけ使う（総額・内需・外需）
    if pdfs["sokuhou"]:
        url = pdfs["sokuhou"][max(pdfs["sokuhou"])]
        month, vals = parse_sokuhou("\n".join(_pdf_pages(url)))
        if month > max(pdfs["kakuhou"], default=pd.Timestamp.min):
            rows.setdefault(month, {}).update(vals)

    out = {}
    for field, ind_id in field_to_id.items():
        s = pd.Series({m: v[field] for m, v in rows.items() if field in v}, dtype=float)
        if not s.empty:
            out[ind_id] = s.sort_index()
    if errors and not out:
        raise ValueError("JMTBA: " + " / ".join(errors[:3]))
    if errors:
        print("  [JMTBA 警告] " + " / ".join(errors[:5]))
    return out
