"""매일 포트폴리오 요약을 Discord Webhook으로 발송하는 독립 실행 스크립트.

실행:  python notify.py [user]      (user 생략 시 .env의 NOTIFY_USER 사용)
스케줄: Windows 작업 스케줄러에서 run_report.bat 을 매일 지정 시각에 실행.

.env 설정 필요:
  DISCORD_WEBHOOK_URL=... (Discord 채널 → 연동 → 웹후크에서 발급)
  NOTIFY_USER=1234       (리포트를 보낼 계정 아이디)
"""
import os
import sys
import json
from datetime import datetime

import requests
from dotenv import load_dotenv

import auth
import pipeline
from ai_copilot import _generate_with_fallback

load_dotenv()


def _daily_path(user):
    return os.path.join(auth.user_dir(user), "daily_metrics.json")


def _load_daily(user):
    p = _daily_path(user)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}
    return {}


def _save_daily(user, date_str, snap):
    data = _load_daily(user)
    data[date_str] = snap
    if len(data) > 120:
        for k in sorted(data.keys())[:-120]:
            data.pop(k, None)
    try:
        with open(_daily_path(user), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def _fmt_krw(n):
    n = float(n or 0)
    if abs(n) >= 1e8:
        return f"{n / 1e8:.2f}억"
    if abs(n) >= 1e4:
        return f"{n / 1e4:,.0f}만"
    return f"{n:,.0f}"


def _ai_comment(text):
    """지표 요약으로 담백한 2~3문장 코멘트를 생성(실패 시 None)."""
    try:
        import google.generativeai as genai
        key = os.getenv("GEMINI_API_KEY")
        if not key or "여기에" in key:
            return None
        genai.configure(api_key=key, transport="rest")
        prompt = (
            "다음은 오늘 한 개인 투자자의 포트폴리오 지표입니다. "
            "투자자에게 도움이 되도록 과장 없이 담백하게 2~3문장으로 코멘트를 한국어로 작성하세요. "
            "수익률이 높아도 위험(베타)·집중도·기간이 짧을 수 있음을 균형있게 언급하세요.\n\n" + text
        )
        resp, _ = _generate_with_fallback(prompt)
        if resp is not None and getattr(resp, "text", None):
            return resp.text.strip()
    except Exception:
        pass
    return None


def build_report(user):
    """계정의 포트폴리오를 로드해 리포트에 필요한 지표를 계산합니다(전일 스냅샷 저장 포함)."""
    pipeline.apply_credentials(user)
    data = pipeline.load_portfolio(user, use_toss=auth.has_toss_credentials(user), use_tx=True)
    summary = data.get("summary") or {}
    ab = data.get("ab") or {}
    total = float(summary.get("total_asset_krw") or 0)

    sa = data.get("stock_analytics")
    stocks_ab = {}
    if sa is not None and not sa.empty:
        for r in sa.to_dict("records"):
            stocks_ab[str(r.get("티커"))] = {
                "alpha": round(float(r.get("알파(연%)") or 0), 2),
                "beta": round(float(r.get("베타") or 0), 3),
                "name": r.get("종목") or "",
            }

    today = datetime.now().strftime("%Y-%m-%d")
    dm = _load_daily(user)
    prev_dates = [d for d in dm.keys() if d < today]
    prev = dm.get(max(prev_dates)) if prev_dates else None
    _save_daily(user, today, {"totalAsset": total, "stocks": {k: {"alpha": v["alpha"], "beta": v["beta"]} for k, v in stocks_ab.items()}})

    delta_line = ""
    if prev:
        pt = float(prev.get("totalAsset") or 0)
        if pt:
            dv = total - pt
            dp = dv / pt * 100
            arrow = "🔺" if dv >= 0 else "🔻"
            delta_line = f"  {arrow} 전일 {'+' if dv >= 0 else ''}{_fmt_krw(dv)}원 ({'+' if dp >= 0 else ''}{dp:.2f}%)"

    # 전일 대비 알파 변동 상위(절대값)
    movers = []
    if prev:
        pstocks = prev.get("stocks") or {}
        for tk, v in stocks_ab.items():
            pv = pstocks.get(tk)
            if pv:
                da = v["alpha"] - float(pv.get("alpha") or 0)
                if abs(da) >= 0.01:
                    movers.append((abs(da), tk, v.get("name") or tk, da))
    movers.sort(reverse=True)

    return {
        "today": today, "total": total, "delta_line": delta_line,
        "xirr": ab.get("port_xirr_pct"), "spy": ab.get("spy_xirr_pct"),
        "alpha": ab.get("alpha_pct"), "beta": ab.get("beta"),
        "movers": movers[:3],
    }


def send_discord(user):
    url = os.getenv("DISCORD_WEBHOOK_URL")
    if not url:
        print("[오류] .env 에 DISCORD_WEBHOOK_URL 이 설정돼 있지 않습니다.")
        return False

    rep = build_report(user)
    xirr_s = f"{rep['xirr']:.2f}%" if rep["xirr"] is not None else "—"
    spy_s = f"{rep['spy']:.2f}%" if rep["spy"] is not None else "—"
    alpha_s = f"{rep['alpha']:+.2f}%p" if rep["alpha"] is not None else "—"
    beta_s = f"{rep['beta']:.2f}" if rep["beta"] is not None else "—"

    fields = [
        {"name": "💰 총자산", "value": f"{_fmt_krw(rep['total'])}원{rep['delta_line']}", "inline": False},
        {"name": "📈 연평균 수익률(XIRR)", "value": f"내 {xirr_s}  ·  S&P500 {spy_s}  ·  알파 {alpha_s}  ·  β {beta_s}", "inline": False},
    ]
    if rep["movers"]:
        mv = "  ·  ".join(
            f"{name} 알파 {'🔺' if da >= 0 else '🔻'}{abs(da):.2f}"
            for _, tk, name, da in rep["movers"]
        )
        fields.append({"name": "🔀 전일 대비 알파 변동", "value": mv, "inline": False})

    fields_text = "\n".join(f"{f['name']}: {f['value']}" for f in fields)
    ai = _ai_comment(fields_text)
    if ai:
        fields.append({"name": "🤖 AI 코멘트", "value": ai[:1000], "inline": False})

    embed = {
        "title": f"📊 {rep['today']} 포트폴리오 리포트",
        "color": 0x00D4A1 if (rep.get("alpha") or 0) >= 0 else 0xFF5C6A,
        "fields": fields,
    }
    r = requests.post(url, json={"embeds": [embed]}, timeout=15)
    ok = 200 <= r.status_code < 300
    print(f"[Discord] status={r.status_code} {'OK' if ok else r.text[:300]}")
    return ok


if __name__ == "__main__":
    user = sys.argv[1] if len(sys.argv) > 1 else os.getenv("NOTIFY_USER", "")
    if not user:
        print("사용법: python notify.py <user>   또는 .env 에 NOTIFY_USER 설정")
        sys.exit(1)
    sys.exit(0 if send_discord(user) else 1)
