import pandas as pd
import pytest

from src import analyze, store

TODAY = pd.Timestamp(2026, 10, 8)


def monthly(values, end="2026-08-01"):
    idx = pd.date_range(end=end, periods=len(values), freq="MS")
    return pd.Series(values, index=idx, dtype=float)


def test_yoy_acceleration_marks_good_when_rising_is_good():
    # 前年は100で一定、今年は 3か月前(5月) +20% → 今月 +30%
    s = monthly([100] * 12 + [105, 108, 110, 112, 120, 125, 130, 128, 120, 125, 128, 130])
    ind = {"freq": "monthly", "yoy": True, "good": "up"}
    a = analyze.summarize(ind, s, TODAY)
    assert a["yoy"] == pytest.approx(30.0)
    assert a["accel"] == pytest.approx(30.0 - 20.0)
    assert a["direction"] == "up" and a["tone"] == "good"


def test_yoy_deceleration_is_bad_even_if_yoy_positive():
    s = monthly([100] * 12 + [150] * 9 + [140, 130, 120])
    a = analyze.summarize({"freq": "monthly", "yoy": True, "good": "up"}, s, TODAY)
    assert a["yoy"] == pytest.approx(20.0)
    assert a["direction"] == "down" and a["tone"] == "bad"


def test_yoy_without_history_falls_back_to_level_chart():
    s = monthly([1, 2, 3])
    a = analyze.summarize({"freq": "monthly", "yoy": True, "good": "up"}, s, TODAY)
    assert a["yoy"] is None and a["direction"] == "none"
    assert a["chart_kind"] == "level"


def test_daily_pct_change_and_neutral_tone():
    idx = pd.bdate_range(end="2026-10-08", periods=300)
    s = pd.Series(range(100, 400), index=idx, dtype=float)
    a = analyze.summarize({"freq": "daily", "good": "neutral"}, s, TODAY)
    assert a["direction"] == "up" and a["tone"] == "neutral"
    assert a["range_pos"] == pytest.approx(100.0)


def test_daily_diff_mode_uses_points():
    idx = pd.bdate_range(end="2026-10-08", periods=120)
    s = pd.Series([4.0] * 60 + [4.5] * 60, index=idx)
    a = analyze.summarize({"freq": "daily", "good": "neutral", "change": "diff"}, s, TODAY)
    three_month = dict((l, v) for l, v, _ in a["metrics"])["3か月"]
    assert three_month == pytest.approx(0.5)


def test_daily_short_history_has_no_long_changes():
    s = pd.Series([1.0, 1.1], index=pd.to_datetime(["2026-10-07", "2026-10-08"]))
    a = analyze.summarize({"freq": "daily", "good": "up"}, s, TODAY)
    assert all(v is None for _, v, _ in a["metrics"])
    assert a["direction"] == "none"


def test_store_upsert_overwrites_same_date(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SERIES_DIR", tmp_path)
    store.upsert("x", pd.Series({pd.Timestamp("2026-01-01"): 1.0, pd.Timestamp("2026-02-01"): 2.0}))
    n = store.upsert("x", pd.Series({pd.Timestamp("2026-02-01"): 3.0, pd.Timestamp("2026-03-01"): 4.0}))
    assert n == 2
    assert list(store.load("x").values) == [1.0, 3.0, 4.0]
