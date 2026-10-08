# 先行指標ダッシュボード

業界統計（半導体・機械・住宅・鉄鋼・観光）と素材価格を中心に、先行指標を 1 ページにまとめる。
Python で取得 → 静的 HTML を生成 → GitHub Actions で平日 19:00 JST に自動更新 → GitHub Pages で閲覧（スマホ前提）。

## 載せている指標

| 区分 | 指標 | 出所 | 頻度 |
|---|---|---|---|
| 業界：半導体 | DRAM・NAND 価格の全品目（手元版のみ） | TrendForce | 日次（このツールが蓄積） |
| | マイクロン、SKハイニックス株価 | Yahoo Finance | 日次 |
| | 日本製半導体製造装置 販売高（手元版のみ）、米半導体生産指数、SOX | SEAJ / FRED / Yahoo | 月次・日次 |
| 業界：機械 | 工作機械受注、産業機械受注、コア機械受注・外需（内閣府） | JMTBA / 産機工 / 内閣府 | 月次 |
| 業界：住宅・建設 | 新設住宅着工（総数・持家・貸家）、米住宅着工許可、木材 | 国交省 / FRED / Yahoo | 月次・日次 |
| 業界：鉄鋼・観光 | 粗鋼生産、訪日外客数（総数・中国） | 鉄鋼連盟 / JNTO | 月次 |
| 素材価格 | 金・銀・プラチナ・パラジウム・銅・アルミ・鉄鉱石・熱延コイル・WTI・天然ガス、リチウム/ウラン/レアアースETF、タングステン（手元版のみ） | Yahoo / 中钨在线 | 日次 |
| 市場ベース | KOSPI、米10年債、米長短金利差（10Y-2Y・10Y-3M）、ドル円 | Yahoo Finance / FRED | 日次 |

指標の追加・削除は `indicators.yaml`、行を押したときに右側に出す関連企業（日本株・米国株）は `baskets.yaml` で編集する。
指標とバスケットの対応は各指標の `related:`。関連企業の株価（現値・騰落率・1か月）は毎日 yfinance で取得する。

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
