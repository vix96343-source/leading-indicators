"""FRED の公開 CSV（API キー不要の fredgraph.csv）。"""
import io

import pandas as pd

from .. import http

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"


def parse_csv(text: str) -> pd.Series:
    df = pd.read_csv(io.StringIO(text))
    date_col, val_col = df.columns[0], df.columns[1]
    s = pd.to_numeric(df[val_col], errors="coerce")
    s.index = pd.to_datetime(df[date_col])
    return s.dropna()


def fetch(indicators: list[dict], today: pd.Timestamp, backfill: bool = False) -> dict[str, pd.Series]:
    start = today - pd.DateOffset(years=12 if backfill else 3)
    out = {}
    for ind in indicators:
        s = parse_csv(http.get(URL.format(series=ind["params"]["series"])).text)
        out[ind["id"]] = s[s.index >= start]
    return out
