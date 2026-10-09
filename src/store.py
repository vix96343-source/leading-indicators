"""系列データの保存: data/series/<id>.csv (date,value)。日付で upsert する。

あわせて data/updated.json に「新しい期間の値が初めて取れた日（JST）」を系列ごとに記録する。
月次統計の公表日の代わりとしてサイトの「更新日」に使う。
"""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SERIES_DIR = ROOT / "data" / "series"
UPDATED_PATH = ROOT / "data" / "updated.json"


def load_updated() -> dict[str, str]:
    if not UPDATED_PATH.exists():
        return {}
    return json.loads(UPDATED_PATH.read_text(encoding="utf-8"))


def _mark_updated(series_id: str) -> None:
    upd = load_updated()
    upd[series_id] = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d")
    UPDATED_PATH.write_text(json.dumps(dict(sorted(upd.items())), ensure_ascii=False, indent=1), encoding="utf-8")


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
    # 新しい期間の値が出たら更新日を記録（値の改定では動かさない）。日次の系列は取引日そのものを使うので記録しない
    if not series_id.startswith(("stk_", "tf_")) and (old.empty or merged.index[-1] > old.index[-1]):
        _mark_updated(series_id)
    return changed
