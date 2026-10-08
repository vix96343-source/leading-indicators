"""全ソースの取得。1ソースの失敗で全体を止めず、結果を data/status.json に残す。"""
import json
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

from . import store
from .sources import fred, jmtba, seaj, tdnet, trendforce, yf

JST = ZoneInfo("Asia/Tokyo")
CONFIG_PATH = store.ROOT / "indicators.yaml"
STATUS_PATH = store.ROOT / "data" / "status.json"
SOURCES = {"trendforce": trendforce, "fred": fred, "yfinance": yf, "jmtba": jmtba, "seaj": seaj}


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def stock_indicators(cfg: dict) -> list[dict]:
    """indicators.yaml の stocks を yfinance 取得用の指標定義に変換する。"""
    return [{"id": f"stock_{it['code']}", "params": {"ticker": f"{it['code']}.T"}}
            for g in cfg["stocks"]["groups"] for it in g["items"]]


def today_jst() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(JST).date())


def run(backfill: bool = False, only: list[str] | None = None, public: bool = False) -> dict:
    cfg = load_config()
    today = today_jst()
    status = json.loads(STATUS_PATH.read_text(encoding="utf-8")) if STATUS_PATH.exists() else {}
    by_source: dict[str, list[dict]] = {}
    for ind in cfg["indicators"]:
        if public and ind.get("restricted"):
            continue  # 公開リポジトリに転載制限のあるデータを残さない
        by_source.setdefault(ind["source"], []).append(ind)

    for name, inds in by_source.items():
        if only and name not in only:
            continue
        now = datetime.now(JST).isoformat(timespec="seconds")
        try:
            got = SOURCES[name].fetch(inds, today, backfill=backfill)
            changed = {k: store.upsert(k, v) for k, v in got.items()}
            missing = [i["id"] for i in inds if i["id"] not in got]
            status[name] = {"ok": True, "at": now, "updated_rows": sum(changed.values()),
                            "message": f"未取得: {', '.join(missing)}" if missing else ""}
            print(f"[{name}] ok  更新 {sum(changed.values())} 行" + (f"  未取得 {missing}" if missing else ""))
        except Exception as e:
            status[name] = {"ok": False, "at": now, "message": f"{type(e).__name__}: {e}"}
            print(f"[{name}] 失敗: {e}")
            traceback.print_exc()

    if (not only or "stocks" in only) and cfg.get("stocks"):
        now = datetime.now(JST).isoformat(timespec="seconds")
        inds = stock_indicators(cfg)
        try:
            got = yf.fetch(inds, today)
            n = sum(store.upsert(k, v) for k, v in got.items())
            missing = [i["params"]["ticker"] for i in inds if i["id"] not in got]
            status["stocks"] = {"ok": True, "at": now, "updated_rows": n,
                                "message": f"未取得: {', '.join(missing)}" if missing else ""}
            print(f"[stocks] ok  更新 {n} 行")
        except Exception as e:
            status["stocks"] = {"ok": False, "at": now, "message": f"{type(e).__name__}: {e}"}
            print(f"[stocks] 失敗: {e}")

    if not only or "tdnet" in only:
        now = datetime.now(JST).isoformat(timespec="seconds")
        try:
            n = tdnet.update(cfg.get("companies", {}), today, backfill=backfill)
            status["tdnet"] = {"ok": True, "at": now, "updated_rows": n, "message": ""}
            print(f"[tdnet] ok  追加 {n} 件")
        except Exception as e:
            status["tdnet"] = {"ok": False, "at": now, "message": f"{type(e).__name__}: {e}"}
            print(f"[tdnet] 失敗: {e}")

    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return status
