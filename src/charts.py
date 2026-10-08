"""依存ライブラリ無しのインライン SVG 折れ線。色は CSS クラスで当てる（テーマ切替対応）。"""
from html import escape

import pandas as pd


def line(s: pd.Series, width: int, height: int, *, zero_line: bool = False,
         axes: bool = False, unit: str = "", tone: str = "neutral") -> str:
    if s is None or len(s) < 2:
        return f'<svg class="chart empty" viewBox="0 0 {width} {height}" role="img" aria-label="データ蓄積中"><text x="{width/2}" y="{height/2}" text-anchor="middle" dominant-baseline="middle">データ蓄積中</text></svg>'
    pad_l, pad_r = (44, 6) if axes else (2, 2)
    pad_t, pad_b = (8, 18) if axes else (3, 3)
    vals = s.astype(float).tolist()
    lo, hi = min(vals), max(vals)
    if zero_line:
        lo, hi = min(lo, 0.0), max(hi, 0.0)
    if hi == lo:
        hi, lo = hi + 1, lo - 1
    t0, t1 = s.index[0].value, s.index[-1].value
    span = (t1 - t0) or 1

    def xy(ts, v):
        x = pad_l + (ts.value - t0) / span * (width - pad_l - pad_r)
        y = pad_t + (hi - v) / (hi - lo) * (height - pad_t - pad_b)
        return x, y

    pts = [xy(ts, v) for ts, v in zip(s.index, vals)]
    d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    # スパークラインは横に伸縮させる。軸付きは文字が歪まないよう比率を保つ
    aspect = "" if axes else ' preserveAspectRatio="none"'
    parts = [f'<svg class="chart tone-{tone}" viewBox="0 0 {width} {height}"{aspect} role="img" '
             f'aria-label="{escape(s.index[0].strftime("%Y-%m-%d"))}〜{escape(s.index[-1].strftime("%Y-%m-%d"))}の推移">']
    if zero_line and lo < 0 < hi:
        _, zy = xy(s.index[0], 0.0)
        parts.append(f'<line class="zero" x1="{pad_l}" x2="{width - pad_r}" y1="{zy:.1f}" y2="{zy:.1f}"/>')
    if axes:
        for v in (hi, lo):
            _, y = xy(s.index[0], v)
            parts.append(f'<line class="grid" x1="{pad_l}" x2="{width - pad_r}" y1="{y:.1f}" y2="{y:.1f}"/>')
            parts.append(f'<text class="axis" x="{pad_l - 4}" y="{y:.1f}" text-anchor="end" dominant-baseline="middle">{escape(fmt_num(v))}{escape(unit)}</text>')
        parts.append(f'<text class="axis" x="{pad_l}" y="{height - 4}">{s.index[0]:%Y/%m}</text>')
        parts.append(f'<text class="axis" x="{width - pad_r}" y="{height - 4}" text-anchor="end">{s.index[-1]:%Y/%m}</text>')
    parts.append(f'<path class="line" d="{d}" vector-effect="non-scaling-stroke"/>')
    if axes:
        lx, ly = pts[-1]
        parts.append(f'<circle class="dot" cx="{lx:.1f}" cy="{ly:.1f}" r="3"/>')
    parts.append("</svg>")
    return "".join(parts)


def fmt_num(v: float) -> str:
    a = abs(v)
    if a >= 1000:
        return f"{v:,.0f}"
    if a >= 100:
        return f"{v:,.1f}"
    if a >= 10:
        return f"{v:,.2f}"
    return f"{v:,.2f}" if a >= 1 else f"{v:,.3f}"
