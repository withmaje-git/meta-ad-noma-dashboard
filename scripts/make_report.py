"""data/insights_daily.csv를 읽어 Slack용 요약+조치 제안 메시지를 만들고 전송.

환경변수:
    SLACK_WEBHOOK_URL : Slack Incoming Webhook URL (없으면 콘솔에만 출력)
    CSV_PATH          : CSV 경로 (기본 data/insights_daily.csv)

조치는 '제안'만 합니다 — 소재 OFF나 예산 변경을 자동 실행하지 않습니다.
"""
import os
import json
import csv
import urllib.request
from collections import defaultdict

APP_URL = "https://meta-ad-noma-dashboard.streamlit.app"
CSV_PATH = os.environ.get("CSV_PATH", "data/insights_daily.csv")
WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL")

# 구매 목적이 아닌(참여/조회/노출) 광고세트는 ROAS 기반 제안에서 제외
NON_PURCHASE_ADSETS = set()

# 임계값 (7일 누적 기준)
LOW_ROAS = 0.5            # 이 미만 + 지출 큰 소재 → OFF 검토
LOW_AD_SPEND = 50000      # 소재 OFF 검토 최소 7일 지출
ZERO_PURCH_SPEND = 30000  # 구매 0인데 이만큼 쓴 소재 → OFF 검토
SCALE_ROAS = 1.3          # 이 이상 + 지출 큰 세트 → 증액 검토
CUT_ROAS = 0.7            # 이 미만인 세트 → 축소/점검
ADSET_MIN_SPEND = 100000  # 세트 예산 제안 최소 7일 지출


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def main():
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit("CSV가 비어 있습니다.")

    dates = sorted({r["date"] for r in rows})
    period = f"{dates[0]} ~ {dates[-1]}"

    a_spend = defaultdict(float); a_pv = defaultdict(float); a_purch = defaultdict(float)
    d_spend = defaultdict(float); d_pv = defaultdict(float); d_purch = defaultdict(float)
    d_adset = {}
    for r in rows:
        a, ad = r["adset"], r["ad"]
        a_spend[a] += num(r["spend"]); a_pv[a] += num(r["purchase_value"]); a_purch[a] += num(r["purchase"])
        d_spend[ad] += num(r["spend"]); d_pv[ad] += num(r["purchase_value"]); d_purch[ad] += num(r["purchase"])
        d_adset[ad] = a

    tot_spend = sum(a_spend.values()); tot_pv = sum(a_pv.values()); tot_purch = sum(a_purch.values())
    tot_roas = tot_pv / tot_spend if tot_spend else 0

    L = []
    L.append(f"*:bar_chart: Meta 광고 리포트*  ({period})")
    L.append(f"대시보드: {APP_URL}")
    L.append("")
    L.append(f"*최근 7일 합계* — 지출 ₩{tot_spend:,.0f} · 구매 {int(tot_purch)}건 "
             f"· 전환값 ₩{tot_pv:,.0f} · *ROAS {tot_roas:.2f}*")
    L.append("")
    L.append("*광고 세트별 성과*")
    for a in sorted(a_spend, key=lambda x: -a_spend[x]):
        if a in NON_PURCHASE_ADSETS:
            L.append(f"•  {a} — 지출 ₩{a_spend[a]:,.0f} · 구매 {int(a_purch[a])}건 _(참여/조회 목적)_")
        else:
            roas = a_pv[a] / a_spend[a] if a_spend[a] else 0
            L.append(f"•  {a} — 지출 ₩{a_spend[a]:,.0f} · 구매 {int(a_purch[a])}건 · ROAS {roas:.2f}")

    recs = []
    for a in sorted(a_spend, key=lambda x: -a_spend[x]):
        if a in NON_PURCHASE_ADSETS or a_spend[a] < ADSET_MIN_SPEND:
            continue
        roas = a_pv[a] / a_spend[a] if a_spend[a] else 0
        if roas >= SCALE_ROAS:
            recs.append(f":arrow_up: *{a}* 예산 증액 검토 — ROAS {roas:.2f} (지출 ₩{a_spend[a]:,.0f})")
        elif roas < CUT_ROAS:
            recs.append(f":arrow_down: *{a}* 예산 축소/점검 — ROAS {roas:.2f} (지출 ₩{a_spend[a]:,.0f})")

    for ad in sorted(d_spend, key=lambda x: -d_spend[x]):
        a = d_adset[ad]
        if a in NON_PURCHASE_ADSETS:
            continue
        roas = d_pv[ad] / d_spend[ad] if d_spend[ad] else 0
        if d_spend[ad] >= LOW_AD_SPEND and roas < LOW_ROAS:
            recs.append(f":no_entry_sign: 소재 *{ad}* OFF 검토 — ROAS {roas:.2f}, 7일 지출 ₩{d_spend[ad]:,.0f}")
        elif d_purch[ad] == 0 and d_spend[ad] >= ZERO_PURCH_SPEND:
            recs.append(f":no_entry_sign: 소재 *{ad}* OFF 검토 — 구매 0, 7일 지출 ₩{d_spend[ad]:,.0f}")

    L.append("")
    if recs:
        L.append("*:pushpin: 조치 제안* _(검토용 — 자동 실행하지 않음)_")
        L.extend(recs)
    else:
        L.append("*:pushpin: 조치 제안* — 특이사항 없음")

    text = "\n".join(L)
    if not WEBHOOK:
        print(text)
        print("\n[WARN] SLACK_WEBHOOK_URL 미설정 — 전송 생략")
        return
    req = urllib.request.Request(
        WEBHOOK, data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        print("slack response:", resp.read().decode())


if __name__ == "__main__":
    main()
