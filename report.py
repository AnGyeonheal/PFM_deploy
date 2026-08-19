"""포트폴리오 검진 결과를 PDF로 출력하는 모듈.

reportlab 내장 CID 한글 폰트(HYSMyeongJo-Medium)를 사용하므로
외부 폰트 파일 없이도 한글이 정상 출력됩니다.
build_portfolio_pdf(...) 가 PDF 바이트를 반환합니다.
"""
import io
import re
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

FONT_NAME = "HYSMyeongJo-Medium"  # reportlab 내장 한글(명조) CID 폰트
_FONT_READY = False

# 토스 스타일 색상
BLUE = colors.HexColor("#3182F6")
BLUE_DARK = colors.HexColor("#1B64DA")
INK = colors.HexColor("#191F28")
SUB = colors.HexColor("#6B7684")
BORDER = colors.HexColor("#E5E8EB")
BG = colors.HexColor("#F2F4F6")
RED = colors.HexColor("#F04452")
GREEN = colors.HexColor("#00A676")


def _ensure_font():
    global _FONT_READY
    if not _FONT_READY:
        pdfmetrics.registerFont(UnicodeCIDFont(FONT_NAME))
        _FONT_READY = True


def _won(v):
    try:
        return f"{float(v):,.0f} 원"
    except (TypeError, ValueError):
        return "-"


def _pct(v, signed=True):
    try:
        return (f"{float(v):+.2f}%" if signed else f"{float(v):.2f}%")
    except (TypeError, ValueError):
        return "-"


def _styles():
    _ensure_font()
    ss = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle("t", parent=ss["Title"], fontName=FONT_NAME,
                                 fontSize=22, leading=28, textColor=INK, spaceAfter=2),
        "subtitle": ParagraphStyle("st", fontName=FONT_NAME, fontSize=10.5,
                                    leading=15, textColor=SUB, alignment=TA_LEFT),
        "h2": ParagraphStyle("h2", fontName=FONT_NAME, fontSize=14, leading=20,
                             textColor=BLUE_DARK, spaceBefore=14, spaceAfter=6),
        "h3": ParagraphStyle("h3", fontName=FONT_NAME, fontSize=12, leading=17,
                             textColor=INK, spaceBefore=8, spaceAfter=4),
        "body": ParagraphStyle("b", fontName=FONT_NAME, fontSize=10, leading=16,
                               textColor=INK),
        "bullet": ParagraphStyle("bl", fontName=FONT_NAME, fontSize=10, leading=16,
                                 textColor=INK, leftIndent=12, bulletIndent=2),
        "small": ParagraphStyle("sm", fontName=FONT_NAME, fontSize=8.5, leading=12,
                                textColor=SUB),
        "cell": ParagraphStyle("c", fontName=FONT_NAME, fontSize=9, leading=12,
                               textColor=INK),
        "cellR": ParagraphStyle("cr", fontName=FONT_NAME, fontSize=9, leading=12,
                                textColor=INK, alignment=2),
    }
    return styles


def _metric_cards(rows, styles, col_count=3):
    """[(label, value, sub_or_None), ...] 를 카드형 표로 렌더링."""
    cells = []
    for label, value, sub in rows:
        parts = [
            Paragraph(f'<font size="8" color="#6B7684">{label}</font>', styles["small"]),
            Spacer(1, 2),
            Paragraph(f'<b>{value}</b>', styles["h3"]),
        ]
        if sub:
            parts.append(Paragraph(f'<font size="8" color="#6B7684">{sub}</font>', styles["small"]))
        cells.append(parts)
    # col_count 개씩 배치
    data = []
    for i in range(0, len(cells), col_count):
        row = cells[i:i + col_count]
        while len(row) < col_count:
            row.append([Spacer(1, 1)])
        data.append(row)
    tbl = Table(data, colWidths=[(170 * mm) / col_count] * col_count)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return tbl


def _md_to_flowables(text, styles):
    """AI가 만든 마크다운 텍스트를 PDF 플로어블 리스트로 간단 변환합니다.
    지원: #/##/### 제목, - / * 불릿, **굵게**, 빈 줄 간격.
    """
    flows = []
    if not text:
        return flows

    def inline(s):
        s = (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"__(.+?)__", r"<b>\1</b>", s)
        s = re.sub(r"`(.+?)`", r"\1", s)
        return s

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flows.append(Spacer(1, 5))
            continue
        if line.startswith("### "):
            flows.append(Paragraph(inline(line[4:]), styles["h3"]))
        elif line.startswith("## "):
            flows.append(Paragraph(inline(line[3:]), styles["h2"]))
        elif line.startswith("# "):
            flows.append(Paragraph(inline(line[2:]), styles["h2"]))
        elif re.match(r"^\s*[-*]\s+", line):
            content = re.sub(r"^\s*[-*]\s+", "", line)
            flows.append(Paragraph("• " + inline(content), styles["bullet"]))
        elif re.match(r"^\s*\d+\.\s+", line):
            flows.append(Paragraph(inline(line.strip()), styles["bullet"]))
        else:
            flows.append(Paragraph(inline(line), styles["body"]))
    return flows


def build_portfolio_pdf(username, source_label, summary=None, perf=None, ab=None,
                        holdings=None, ai_report=None, fx_rate=None):
    """포트폴리오 검진 PDF를 생성해 bytes로 반환합니다.

    username: 사용자 이름
    source_label: 데이터 소스 표시명
    summary: asset_summary dict
    perf: 성과 요약 dict (compute_performance_summary)
    ab: 알파/베타 dict (compute_alpha_beta)
    holdings: 보유 종목 dict 리스트
    ai_report: AI 진단(리밸런싱) 마크다운 텍스트(선택)
    fx_rate: 적용 환율(선택)
    """
    styles = _styles()
    summary = summary or {}
    perf = perf or {}
    ab = ab or {}
    holdings = holdings or []

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=16 * mm,
        title="자산관리 검진 리포트", author="자산관리 대시보드",
    )
    story = []

    # ── 헤더 ──
    story.append(Paragraph("📈 자산관리 검진 리포트", styles["title"]))
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    meta = f"사용자 <b>{username}</b> · 데이터 소스 {source_label} · 생성 {now}"
    if fx_rate:
        meta += f" · 적용 환율 1 USD = {fx_rate:,.1f} KRW"
    story.append(Paragraph(meta, styles["subtitle"]))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER))

    # ── 1. 자산 요약 ──
    story.append(Paragraph("1. 자산 요약", styles["h2"]))
    krw_cash = float(summary.get("cash_krw_native", 0) or 0)
    usd_cash = float(summary.get("cash_usd_native", 0) or 0)
    cards = [
        ("총자산", _won(summary.get("total_asset_krw", 0)), None),
        ("주식 평가액", _won(summary.get("stock_eval_krw", 0)), None),
        ("투자 원금", _won(summary.get("purchase_krw", 0)), None),
        ("예수금 (원화)", _won(krw_cash), None),
        ("예수금 (달러)", f"$ {usd_cash:,.2f}", None),
        ("적용 환율", f"{float(summary.get('fx_rate', fx_rate or 0) or 0):,.1f} 원/$", None),
    ]
    story.append(_metric_cards(cards, styles, col_count=3))

    # ── 2. 성과 · 위험 지표 (알파/베타) ──
    story.append(Paragraph("2. 성과 · 위험 지표 (알파/베타)", styles["h2"]))
    ab_cards = [
        ("연환산 수익률 (XIRR)", _pct(ab.get("port_xirr_pct")), "내 포트폴리오"),
        ("S&P500 XIRR", _pct(ab.get("spy_xirr_pct")), "동일 현금흐름"),
        ("알파 (초과수익)", _pct(ab.get("alpha_pct")),
         "벤치마크 상회" if (ab.get("alpha_pct") or 0) >= 0 else "벤치마크 하회"),
        ("베타 (시장 민감도)", f"{ab.get('beta')}" if ab.get("beta") is not None else "-",
         _beta_desc(ab.get("beta"))),
        ("상관계수", f"{ab.get('corr')}" if ab.get("corr") is not None else "-", None),
        ("측정 기간", f"{ab.get('n_days', 0)} 거래일", None),
    ]
    story.append(_metric_cards(ab_cards, styles, col_count=3))

    if perf:
        story.append(Paragraph("손익 구성", styles["h3"]))
        perf_cards = [
            ("누적 총손익", _won(perf.get("all_inclusive_krw", 0)),
             _pct(perf.get("all_inclusive_pct")) + " (원금대비)"),
            ("보유 평가손익", _won(perf.get("unreal_total_krw", 0)),
             _pct(perf.get("unreal_total_pct"))),
            ("실현손익", _won(perf.get("realized_total_krw", 0)), "매도 확정"),
            ("순수 주가손익", _won(perf.get("pure_price_krw", 0)), None),
            ("배당 수익", _won(perf.get("div_krw", 0)), "추정·합산"),
            ("환차손익", _won(perf.get("fx_total_krw", 0)),
             "환율 이익" if (perf.get("fx_total_krw") or 0) >= 0 else "환율 손실"),
        ]
        story.append(_metric_cards(perf_cards, styles, col_count=3))

    # ── 3. 보유 종목 ──
    if holdings:
        story.append(Paragraph("3. 보유 종목", styles["h2"]))
        header = ["종목명", "티커", "비중(%)", "평가액(원)", "수익률(%)"]
        data = [[Paragraph(f"<b>{h}</b>", styles["cell"]) for h in header]]
        for h in holdings[:25]:
            ret = h.get("return_pct", 0)
            ret_color = "#00A676" if (ret or 0) >= 0 else "#F04452"
            data.append([
                Paragraph(str(h.get("name", "") or h.get("ticker", "")), styles["cell"]),
                Paragraph(str(h.get("ticker", "")), styles["cell"]),
                Paragraph(f'{float(h.get("weight_pct", 0) or 0):.2f}', styles["cellR"]),
                Paragraph(f'{float(h.get("eval_krw", 0) or 0):,.0f}', styles["cellR"]),
                Paragraph(f'<font color="{ret_color}">{float(ret or 0):+.2f}</font>', styles["cellR"]),
            ])
        tbl = Table(data, colWidths=[52 * mm, 24 * mm, 26 * mm, 40 * mm, 28 * mm], repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BG),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, BORDER),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFBFC")]),
            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(tbl)

    # ── 4. AI 진단 · 리밸런싱 제안 ──
    if ai_report:
        story.append(Paragraph("4. AI 진단 · 리밸런싱 제안 (알파·베타 관점)", styles["h2"]))
        story.extend(_md_to_flowables(ai_report, styles))

    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=0.6, color=BORDER))
    story.append(Paragraph(
        "본 리포트는 시세·환율 데이터 기반 추정치를 포함하며 투자 자문이 아닙니다. "
        "실제 투자 판단과 책임은 사용자 본인에게 있습니다.", styles["small"]))

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()


def _beta_desc(beta):
    if beta is None:
        return None
    try:
        b = float(beta)
    except (TypeError, ValueError):
        return None
    if b > 1.1:
        return "공격적(시장>1)"
    if abs(b - 1) <= 0.1:
        return "시장과 유사"
    return "방어적(시장<1)"
