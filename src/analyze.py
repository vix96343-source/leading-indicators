"""系列から表示用の数値（変化率・前年比・加速・方向）を計算する。"""
import pandas as pd

# 方向判定のしきい値（これ未満の変化は「横ばい」）
DAILY_PCT = 3.0       # 日次: 3か月変化率 %
DAILY_DIFF = 0.15     # 日次・差分型（金利など）: 3か月差 pt
YOY_ACCEL_PT = 2.0    # 月次・前年比型: 前年比の3か月前からの変化 pt
LEVEL_PCT = 0.5       # 月次・水準型: 3か月変化率 %
LEVEL_DIFF = 3.0      # 月次・水準型・差分（DI など）: 3か月差 pt

STALE_DAYS = {"daily": 7, "monthly": 80}


def _asof(s: pd.Series, when: pd.Timestamp):
    """when 以前で最も新しい値。無ければ None。"""
    s = s[s.index <= when]
    return None if s.empty else float(s.iloc[-1])


def _pct(a, b):
    if a is None or b is None or b == 0:
        return None
    return (a / b - 1) * 100


def yoy_series(s: pd.Series) -> pd.Series:
    """月次系列の前年同月比 %（前年同月の値がある月だけ）。"""
    prev = s.copy()
    prev.index = prev.index + pd.DateOffset(years=1)
    both = pd.concat([s.rename("now"), prev.rename("prev")], axis=1).dropna()
    return ((both["now"] / both["prev"] - 1) * 100).rename("yoy")


def summarize(ind: dict, s: pd.Series, today: pd.Timestamp) -> dict:
    out = {"n": int(len(s)), "latest": None, "direction": "none", "tone": "neutral", "metrics": []}
    if s.empty:
        return out
    last_date, last = s.index[-1], float(s.iloc[-1])
    out.update(latest=last, latest_date=last_date,
               stale=(today - last_date).days > ind.get("stale_days", STALE_DAYS[ind["freq"]]))
    diff_mode = ind.get("change") == "diff"

    if ind["freq"] == "daily":
        def chg(days):
            base = _asof(s, last_date - pd.Timedelta(days=days))
            if base is None or (s.index[0] > last_date - pd.Timedelta(days=days - 3)):
                return None
            return last - base if diff_mode else _pct(last, base)
        c1w, c1m, c3m, c1y = chg(7), chg(30), chg(91), chg(365)
        unit = "pt" if diff_mode else "%"
        out["metrics"] = [("1週", c1w, unit), ("1か月", c1m, unit), ("3か月", c3m, unit), ("1年", c1y, unit)]
        window = s[s.index > last_date - pd.Timedelta(days=365)]
        if len(window) >= 20 and window.max() > window.min():
            out["range_pos"] = (last - window.min()) / (window.max() - window.min()) * 100
        basis = c3m if c3m is not None else c1m if c1m is not None else c1w
        thr = DAILY_DIFF if diff_mode else DAILY_PCT
        out["direction"] = _direction(basis, thr)
        out["recent"] = list(s.iloc[-10:][::-1].items())
    else:
        out["recent"] = list(s.iloc[-13:][::-1].items())
        if ind.get("yoy"):
            y = yoy_series(s)
            y_now = float(y.iloc[-1]) if not y.empty and y.index[-1] == last_date else None
            y_3m = _asof(y, last_date - pd.DateOffset(months=3))
            y_3m = y_3m if y_3m is not None and y.index[0] <= last_date - pd.DateOffset(months=3) else None
            accel = y_now - y_3m if y_now is not None and y_3m is not None else None
            mom = _pct(last, _asof(s, last_date - pd.DateOffset(months=1)))
            out["metrics"] = [("前年比", y_now, "%"), ("3か月前", y_3m, "%"),
                              ("加速", accel, "pt"), ("前月比", mom, "%")]
            out["yoy"], out["accel"] = y_now, accel
            out["direction"] = _direction(accel, YOY_ACCEL_PT)
            out["recent_yoy"] = {d: v for d, v in y.items()}
        else:
            def chg(months):  # 差分型（DI など負になりうる指数）は pt 差、それ以外は変化率
                base = _asof(s, last_date - pd.DateOffset(months=months))
                if base is None:
                    return None
                return last - base if diff_mode else _pct(last, base)
            c1, c3, c12 = chg(1), chg(3), chg(12)
            unit = "pt" if diff_mode else "%"
            out["metrics"] = [("前月比", c1, unit), ("3か月", c3, unit), ("前年比", c12, unit)]
            out["direction"] = _direction(c3, LEVEL_DIFF if diff_mode else LEVEL_PCT)

    good = ind.get("good", "neutral")
    if out["direction"] in ("up", "down") and good in ("up", "down"):
        out["tone"] = "good" if out["direction"] == good else "bad"
    return out


def _direction(v, threshold):
    if v is None:
        return "none"
    if v >= threshold:
        return "up"
    if v <= -threshold:
        return "down"
    return "flat"
