# 先行指標ダッシュボード

メモリ価格・業界統計（受注・出荷）・海外の景気先行指標・市場ベースの指標を 1 ページにまとめる。
Python で取得 → 静的 HTML を生成 → GitHub Actions で平日 19:00 JST に自動更新 → GitHub Pages で閲覧（スマホ前提）。

## 載せている指標

| 区分 | 指標 | 出所 | 頻度 |
|---|---|---|---|
| メモリ価格 | DDR5/DDR4 スポット、NAND ウェハ | TrendForce | 日次（このツールが蓄積） |
| | マイクロン、SKハイニックス株価 | Yahoo Finance | 日次 |
| 業界統計 | 工作機械受注（総額・内需・外需・中国・内需電気精密） | 日本工作機械工業会 | 月次（2015年〜） |
| | 日本製半導体製造装置 販売高（3か月移動平均） | 日本半導体製造装置協会 | 月次（蓄積） |
| 景気先行（海外） | 米コア資本財受注、米製造業新規受注、米半導体生産指数、韓国輸出、OECD CLI（日米） | FRED | 月次 |
| 市場ベース | SOX、銅、ドライバルク運賃ETF、KOSPI、米10年債、米長短金利差、ドル円 | Yahoo Finance / FRED | 日次 |

指標の追加・削除・ウォッチリストの変更は `indicators.yaml` だけで行う。

## 判定の見方

- **日次**: 3か月の変化で上昇/下落（±3%、金利は ±0.15pt 未満は横ばい）。過去1年レンジ内の位置も表示。
- **月次（前年比型）**: 前年比が 3か月前と比べて 2pt 以上上がれば「加速」、下がれば「減速」。
  前年比がプラスでも減速なら逆風扱い（ピークアウトの兆候）、マイナスでも加速なら追い風扱い（底入れの兆候）。
- 色は `good`（上昇が関連銘柄の追い風か）で決める。金利・為替は中立。

## 使い方

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m src.cli fetch --backfill   # 初回のみ（数分）
.venv\Scripts\python -m src.cli build              # local/index.html（全指標）を生成
.venv\Scripts\python -m src.cli run                # fetch → build（日次処理）
.venv\Scripts\python -m src.cli run --public       # 公開版 docs/index.html
.venv\Scripts\python -m src.cli fetch --only jmtba,seaj
.venv\Scripts\python -m pytest -q
```

## 公開版と全指標版

TrendForce と SEAJ のデータは転載制限がある（SEAJ は「許可なく転載・公表を禁止」と明記）ため、
`indicators.yaml` で `restricted: true` にして 2 系統に分けている。

| | 公開版（GitHub Pages） | 全指標版（手元） |
|---|---|---|
| コマンド | `python -m src.cli run --public` | `python -m src.cli run` |
| 出力 | `docs/index.html` | `local/index.html`（git 管理外） |
| TrendForce・SEAJ | 取得も表示もしない | 含む |
| 更新 | GitHub Actions が平日 19:00 JST | 手動（またはタスクスケジューラ） |

- 制限付きデータの CSV（`data/series/dram_*`・`nand_*`・`seaj_*`）は `.gitignore` 済みで、手元にだけ貯まる。
  メモリスポット価格の履歴を貯めたい場合は、手元で毎営業日 `run` を実行する。
- 手元で実行する前に `git pull` して、Actions が更新したデータを取り込んでおく。

## 仕組み

```
indicators.yaml ─┐
                 ├─ src/fetch.py ── sources/{trendforce,jmtba,seaj,fred,yf}.py
                 │        └→ data/series/<id>.csv（日付で upsert）, data/status.json
                 └─ src/build.py ── analyze.py（変化率・前年比・加速）+ charts.py（SVG）
                          └→ docs/index.html（templates/index.html.j2）
```

- 1 ソースが失敗しても他は続行し、ページ下部の「データ取得状況」に失敗理由を出す。
- スクレイピングはホストごとに 1 リクエスト/秒、User-Agent 明示、失敗時 3 回リトライ。
- TrendForce と SEAJ は当日（直近）の値しか取れないため、履歴は日々の取得で貯まっていく。
  SEAJ は初回だけ、PDF の前年比から前年同月の値を逆算して埋めている。
