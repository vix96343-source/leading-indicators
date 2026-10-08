"""系列データの保存: data/series/<id>.csv (date,value)。日付で upsert する。"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SERIES_DIR = ROOT / "data" / "series"


def path_for(series_id: str) -> Path:
    return SERIES_DIR / f"{series_id}.csv"


def load(series_id: str) -> pd.Series:
    p = path_for(series_id)
    if not p.exists():
        return pd.Series(dtype=float, name=series_id)
    df = pd.read_csv(p, parse_dates=["date"])
    return df.set_index("date")["value"].astype(float).rename(series_id).sort_index()


def upsert(series_id: str, new: pd.Series) -> int:
    """new (index=日付, 値) を既存に上書きマージ。追加・更新された行数を返す。"""
    new = new.dropna()
    new.index = pd.to_datetime(new.index).normalize()
    new = new[~new.index.duplicated(keep="last")].astype(float)
    old = load(series_id)
    kept = old[~old.index.isin(new.index)]
    merged = (pd.concat([kept, new]) if not kept.empty else new).sort_index()
    changed = int((~new.index.isin(old.index)).sum()
                  + (old.reindex(new.index).sub(new).abs() > 1e-8 * new.abs().clip(lower=1)).sum())  # 保存時の丸め差は無視
    SERIES_DIR.mkdir(parents=True, exist_ok=True)
    out = merged.rename("value").to_frame()
    out.index.name = "date"
    out.to_csv(path_for(series_id), date_format="%Y-%m-%d", float_format="%.10g")
    return changed
