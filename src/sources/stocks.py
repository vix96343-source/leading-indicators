"""関連企業（baskets.yaml）の株価。yfinance でまとめて取得し data/series/stk_<シンボル>.csv に保存する。"""
import re

import pandas as pd
import yaml
import yfinance as yf

from .. import store
from .yf import clean

BASKETS_PATH = store.ROOT / "baskets.yaml"


def load_baskets() -> dict:
    with open(BASKETS_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def yahoo_symbol(market: str, code: str) -> str:
    return f"{code}.T" if market == "jp" else code


def series_id(symbol: str) -> str:
    return "stk_" + re.sub(r"[^A-Za-z0-9]+", "_", symbol)


def all_symbols(baskets: dict) -> list[str]:
    return sorted({yahoo_symbol(m, c) for b in baskets.values() for m in ("jp", "us") for c, _ in b.get(m) or []})


def fetch(today: pd.Timestamp, backfill: bool = False) -> tuple[dict[str, pd.Series], list[str]]:
    symbols = all_symbols(load_baskets())
    data = yf.download(symbols, period="1y" if backfill else "3mo", auto_adjust=True,
                       progress=False, group_by="ticker", threads=True)
    out, missing = {}, []
    for sym in symbols:
        try:
            close = data[sym]["Close"].dropna()
        except KeyError:
            close = pd.Series(dtype=float)
        if close.empty:
            missing.append(sym)
            continue
        close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
        out[series_id(sym)] = clean(close)
    return out, missing
