"""PDF 리포트용 차트 이미지(PNG) 생성 — matplotlib(Agg).
서버/도커 어디서나 안전하도록 라벨은 영문(ASCII)·티커를 사용합니다.
"""
import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter


def _won_fmt(v, _pos=None):
    v = float(v)
    if abs(v) >= 1e9:
        return f"{v / 1e9:.1f}B"
    if abs(v) >= 1e7:
        return f"{v / 1e6:.0f}M"
    if abs(v) >= 1e6:
        return f"{v / 1e6:.1f}M"
    if abs(v) >= 1e3:
        return f"{v / 1e3:.0f}K"
    return f"{v:.0f}"


def growth_png(gdf, title="Asset Growth vs S&P500 (KRW)"):
    """성장 프레임(build_asset_value_growth) → PNG bytes. 없으면 None.
    개별 종목이면 '주가'를 보조축으로 함께 그립니다."""
    if gdf is None or getattr(gdf, "empty", True):
        return None
    idx = gdf.index
    fig, ax = plt.subplots(figsize=(8.2, 3.7), dpi=140)
    lines = []
    if "내 자산가치" in gdf:
        lines += ax.plot(idx, gdf["내 자산가치"], color="#EF553B", lw=2.0, label="My Assets")
    if "S&P500 자산가치" in gdf:
        lines += ax.plot(idx, gdf["S&P500 자산가치"], color="#636EFA", lw=1.6, ls="--", label="S&P500 (sell-adj)")
    if "순투자원금" in gdf:
        lines += ax.plot(idx, gdf["순투자원금"], color="#9AA4AE", lw=1.2, ls=":", label="Net Principal")
    if "내 누적손익" in gdf:
        ax.fill_between(idx, gdf["내 누적손익"], color="#14B8A6", alpha=0.12)
        lines += ax.plot(idx, gdf["내 누적손익"], color="#14B8A6", lw=1.4, label="Cumulative P&L")
    ax.yaxis.set_major_formatter(FuncFormatter(_won_fmt))
    ax.grid(True, alpha=0.25)
    ax.tick_params(labelsize=8)
    if "주가" in gdf:
        ax2 = ax.twinx()
        lines += ax2.plot(idx, gdf["주가"], color="#F9A825", lw=1.1, alpha=0.85, label="Price (native)")
        ax2.tick_params(labelsize=8)
        ax2.set_ylabel("Price", fontsize=8)
    ax.set_title(title, fontsize=11)
    ax.legend(lines, [ln.get_label() for ln in lines], loc="upper left", fontsize=8, framealpha=0.85)
    fig.autofmt_xdate(rotation=0, ha="center")
    return _to_png(fig)


def allocation_png(holdings):
    """보유 비중 파이 → PNG bytes. 없으면 None."""
    hs = [h for h in (holdings or []) if float(h.get("weight_pct") or 0) > 0]
    if not hs:
        return None
    hs = sorted(hs, key=lambda h: -float(h.get("weight_pct") or 0))
    top = hs[:11]
    labels = [str(h.get("ticker") or "") for h in top]
    sizes = [float(h.get("weight_pct") or 0) for h in top]
    rest = sum(float(h.get("weight_pct") or 0) for h in hs[11:])
    if rest > 0:
        labels.append("Others")
        sizes.append(rest)
    fig, ax = plt.subplots(figsize=(5.0, 4.0), dpi=140)
    ax.pie(sizes, labels=labels, autopct="%1.0f%%", startangle=90,
           textprops={"fontsize": 7}, pctdistance=0.8)
    ax.set_title("Holdings Allocation (%)", fontsize=11)
    ax.axis("equal")
    return _to_png(fig)


def _to_png(fig):
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
