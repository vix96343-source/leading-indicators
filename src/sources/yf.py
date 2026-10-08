"""yfinance の日次終値。"""
import pandas as pd
import yfinance as yf

MAX_DAILY_JUMP = 0.30  # 前日比 ±30% 超は欠損・分割未調整を疑って捨てる


def clean(close: pd.Series) -> pd.Series:
    close = close.dropna()
    jump = close.pct_change().abs()
    # 単発のスパイク（翌日に元へ戻る）だけを落とす。本物の急変は残す
    spike = (jump > MAX_DAILY_JUMP) & (close.pct_change(-1).abs() > MAX_DAILY_JUMP)
    return close[~spike]


def fetch(indicators: list[dict], today: pd.Timestamp, backfill: bool = False) -> dict[str, pd.Series]:
    out = {}
    for ind in indicators:
        hist = yf.Ticker(ind["params"]["ticker"]).history(
            period="10y" if backfill else "3mo", auto_adjust=True)
        if hist.empty:
            raise ValueError(f"yfinance: {ind['params']['ticker']} のデータが空")
        close = hist["Close"]
        close.index = close.index.tz_localize(None).normalize()
        out[ind["id"]] = clean(close)
    return out
