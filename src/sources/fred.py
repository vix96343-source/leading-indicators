"""FRED の月次・日次系列。

環境変数 FRED_API_KEY があれば公式 API（クラウドからも安定）、無ければキー不要の fredgraph.csv を使う。
fredgraph.csv は GitHub Actions など共有 IP からだとタイムアウトしやすい。
"""
import io
import os

import pandas as pd

from .. import http

CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
API_URL = ("https://api.stlouisfed.org/fred/series/observations"
           "?series_id={series}&api_key={key}&file_type=json&observation_start={start}")


def parse_csv(text: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(text))
    date_col, val_col = df.columns[0], df.columns[1]
    s = pd.to_numeric(df[val_col], errors="coerce")
    s.index = pd.to_datetime(df[date_col])
    return s.dropna()


def parse_api(obj: dict) -> pd.Series:
    obs = obj.get("observations", [])
    s = pd.Series({pd.Timestamp(o["date"]): o["value"] for o in obs}, dtype=object)
    return pd.to_numeric(s, errors="coerce").dropna()


def fetch_one(series: str, start: pd.Timestamp) -> pd.Series:
    key = os.environ.get("FRED_API_KEY")
    if key:
        s = parse_api(http.get(API_URL.format(series=series, key=key, start=f"{start:%Y-%m-%d}"), timeout=60).json())
    else:
        s = parse_csv(http.get(CSV_URL.format(series=series), timeout=60).text)
    return s[s.index >= start]


def fetch(indicators: list[dict], today: pd.Timestamp, backfill: bool = False) -> dict[str, pd.Series]:
    start = today - pd.DateOffset(years=12 if backfill else 3)
    out, errors = {}, []
    for ind in indicators:
        try:  # 1系列の失敗で他を止めない（取れなかった系列は status に「未取得」と出る）
            out[ind["id"]] = fetch_one(ind["params"]["series"], start)
        except Exception as e:
            errors.append(f"{ind['params']['series']}: {type(e).__name__}")
            if len(errors) >= 2 and not out:
                break  # 接続自体が通らない（IP 制限など）。残りもリトライ待ちで時間を浪費するだけ
    if not out:
        raise RuntimeError("FRED: 全系列失敗 " + " / ".join(errors))
    return out
