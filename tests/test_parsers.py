"""各ソースのパーサを固定入力で確認する（ネットワーク不要）。

fixtures/ は実際の PDF・ページと同じ並び（ラベルと改行の位置）を再現した合成データで、数値は架空。
"""
from pathlib import Path

import pandas as pd
import pytest

from src.sources import fred, jmtba, seaj, trendforce

FX = Path(__file__).parent / "fixtures"


def read(name):
    return (FX / name).read_text(encoding="utf-8")


def test_jmtba_kakuhou_current_layout():
    v = jmtba.parse_kakuhou([read("kakuhou_new_p0.txt"), read("kakuhou_new_p1.txt")])
    assert v == {"total": 100000, "domestic": 30000, "foreign": 70000,
                 "elec_precision": 2345, "china": 25000}


def test_jmtba_kakuhou_old_layout_china_with_fullwidth_spaces():
    v = jmtba.parse_kakuhou([read("kakuhou_old_p0.txt"), read("kakuhou_old_p1.txt")])
    assert v["china"] == 33333
    assert v["total"] == v["domestic"] + v["foreign"]


def test_jmtba_kakuhou_rejects_inconsistent_totals():
    p0 = read("kakuhou_new_p0.txt").replace("70,000", "99,999", 1)
    with pytest.raises(ValueError):
        jmtba.parse_kakuhou([p0, read("kakuhou_new_p1.txt")])


def test_jmtba_sokuhou():
    month, v = jmtba.parse_sokuhou(read("sokuhou.txt"))
    assert month == pd.Timestamp(2026, 8, 1)
    assert v == {"total": 100000, "domestic": 30000, "foreign": 70000}


def test_jmtba_list_pdfs():
    html = ('<a href="https://www.jmtba.or.jp/wjmtbap/wp-content/uploads/2026/10/kakuhou2608.pdf">'
            '<a href="https://www.jmtba.or.jp/wjmtbap/wp-content/uploads/2026/09/sokuhou2609.pdf">')
    got = jmtba.list_pdfs(html)
    assert list(got["kakuhou"]) == [pd.Timestamp(2026, 8, 1)]
    assert list(got["sokuhou"]) == [pd.Timestamp(2026, 9, 1)]


def test_seaj_release_and_implied_prior_year():
    actual, implied = seaj.parse_release(read("seaj_release.txt"))
    assert actual[pd.Timestamp(2026, 8, 1)] == 220000  # 「2026/8(暫定値)」の行
    assert actual[pd.Timestamp(2026, 7, 1)] == 200000  # 「2026/7(確定値)」の行
    assert len(actual) == 2
    # 2026/8 は前年比 +10% → 2025/8 = 220,000 / 1.1
    assert implied[pd.Timestamp(2025, 8, 1)] == 200000


def test_trendforce_all_items():
    rows = trendforce.parse_page(read("trendforce_table.html"), "dram")
    got = [(r["section"], r["item"], r["avg"], r["chg"]) for r in rows]
    assert got == [
        ("DRAM スポット", "DDR5 16Gb (2Gx8) 4800/5600", 9.125, 1.0),  # 連続空白は1つに正規化
        ("DRAM スポット", "DDR4 8Gb (1Gx8) 3200", 6.5, -0.5),
        ("DRAM 契約", "1TB SSD", 250.0, None),           # 名前だけの表は飛ばし、注記行も無視
        ("DRAMモジュール スポット", "ACME X1 1 TB", 95.0, 0.0),  # Brand 表はブランド・シリーズ・容量で1品目
    ]
    assert rows[0]["id"] == "tf_dram_ddr5_16gb_2gx8_4800_5600"


def test_fred_csv_skips_missing():
    s = fred.parse_csv("observation_date,X\n2026-01-01,1.5\n2026-02-01,.\n2026-03-01,2\n")
    assert list(s.values) == [1.5, 2.0]


def test_fred_api_json():
    s = fred.parse_api({"observations": [{"date": "2026-01-01", "value": "1.5"},
                                         {"date": "2026-02-01", "value": "."}]})
    assert list(s.values) == [1.5]

