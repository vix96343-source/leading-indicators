"""エントリポイント。GitHub Actions も手動実行も同じコマンドを呼ぶ。

  python -m src.cli fetch [--backfill] [--only trendforce,fred] [--public]
  python -m src.cli build [--public]
  python -m src.cli run   [--public]          # fetch → build

--public: 転載制限のある指標（indicators.yaml の restricted: true）を除外し docs/ に出力（GitHub Pages 用）。
          付けなければ全指標を local/index.html に出力（手元で見る用）。
"""
import argparse
import sys

from . import build, fetch


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="python -m src.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="データ取得")
    f.add_argument("--backfill", action="store_true", help="過去分をまとめて取得（初回用）")
    f.add_argument("--only", help="カンマ区切りのソース名 (trendforce,fred,yfinance,jmtba,seaj,esri,industry_jp,ctia,stocks)")
    f.add_argument("--public", action="store_true", help="転載制限のある指標を取得しない")
    b = sub.add_parser("build", help="HTML生成")
    b.add_argument("--public", action="store_true", help="転載制限のある指標を除外して docs/ に出力")
    r = sub.add_parser("run", help="fetch → build")
    r.add_argument("--public", action="store_true")
    args = p.parse_args(argv)

    if args.cmd in ("fetch", "run"):
        only = args.only.split(",") if getattr(args, "only", None) else None
        fetch.run(backfill=getattr(args, "backfill", False), only=only, public=args.public)
    if args.cmd in ("build", "run"):
        print("生成:", build.build(public=args.public))


if __name__ == "__main__":
    main()
