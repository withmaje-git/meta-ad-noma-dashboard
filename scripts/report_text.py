"""data/insights_daily.csv에서 슬랙용 일일 리포트 '문구'를 만들어 stdout에 출력.

전송은 하지 않는다(클라우드 루틴이 Slack 커넥터로 스레드에 붙임).
- '새 판매 캠페인'은 리포트에서 제외.
- 최근 7일 합계 + 어제(최신일) 지표(7일 일평균 대비) + 광고세트별 어제 지표 + 조치 제안.
"""
import os
import csv
from collections import defaultdict

CSV_PATH = os.environ.get("CSV_PATH", "data/insights_daily.csv")
EXCLUDE_CAMPAIGNS = {"새 판매 캠페인"}

# 임계값 (7일 누적 기준)
ADSET_MIN_SPEND = 30000   # 세트 예산 제안 최소 7일 지출
SCALE_ROAS = 1.3          # 이 이상 → 증액 검토
CUT_ROAS = 0.7            # 이 미만 → 축소/점검
LOW_AD_SPEND = 30000      # 소재 OFF 검토 최소 7일 지출
LOW_ROAS = 0.5            # 이 미만 + 지출 큰 소재 → OFF 검토
ZERO_PURCH_SPEND = 20000  # 구매 0인데 이만큼 쓴 소재 → OFF 검토


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def main():
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r["campaign"] not in EXCLUDE_CAMPAIGNS]
    if not rows:
        print("CSV가 비어 있습니다.")
        return

    dates = sorted({r["date"] for r in rows})
    latest = dates[-1]
    last7 = set(dates[-7:])

    # 계정 전체 — 최근 7일 / 어제
    def agg(pred):
        s = v = p = 0.0
        for r in rows:
            if pred(r):
                s += num(r["spend"]); v += num(r["purchase_value"]); p += num(r["purchase"])
        return s, v, p

    s7, v7, p7 = agg(lambda r: r["date"] in last7)
    sy, vy, py = agg(lambda r: r["date"] == latest)
    r7 = v7 / s7 if s7 else 0
    ry = vy / sy if sy else 0
    ndays = len(last7)
    avg_s = s7 / ndays if ndays else 0

    L = []
    L.append(f"📊 **노마디아 메타광고 리포트** — {latest}")
    L.append(f"**최근 7일** 지출 ₩{s7:,.0f} · 구매 {int(p7)}건 · 매출 ₩{v7:,.0f} · **ROAS {r7:.2f}**")
    L.append(f"**어제({latest[5:]})** 지출 ₩{sy:,.0f} · 구매 {int(py)}건 · 매출 ₩{vy:,.0f} · **ROAS {ry:.2f}**"
             f"  _(어제 지출 vs 7일 일평균 ₩{avg_s:,.0f})_")

    # 광고세트별 — 어제 지출>0
    a_s = defaultdict(float); a_v = defaultdict(float); a_p = defaultdict(float)   # 어제
    w_s = defaultdict(float); w_v = defaultdict(float); w_p = defaultdict(float)   # 7일
    for r in rows:
        a = r["adset"]
        if r["date"] == latest:
            a_s[a] += num(r["spend"]); a_v[a] += num(r["purchase_value"]); a_p[a] += num(r["purchase"])
        if r["date"] in last7:
            w_s[a] += num(r["spend"]); w_v[a] += num(r["purchase_value"]); w_p[a] += num(r["purchase"])

    active = sorted([a for a in a_s if a_s[a] > 0])   # 광고세트 이름 오름차순
    if active:
        L.append("")
        L.append("**광고세트별 (어제)**")
        for a in active:
            roas = a_v[a] / a_s[a] if a_s[a] else 0
            L.append(f"•  {a} — 지출 ₩{a_s[a]:,.0f} · 구매 {int(a_p[a])}건 · ROAS {roas:.2f}")

    # 조치 제안 — 7일 기준, 어제 지출 0(이미 중단) 세트는 제외
    recs = []
    for a in sorted(w_s, key=lambda x: -w_s[x]):
        if a_s.get(a, 0) <= 0:
            continue
        roas = w_v[a] / w_s[a] if w_s[a] else 0
        if w_s[a] >= ADSET_MIN_SPEND and roas >= SCALE_ROAS:
            recs.append(f"⬆️ **{a}** 예산 증액 검토 — 7일 ROAS {roas:.2f} (지출 ₩{w_s[a]:,.0f})")
        elif w_s[a] >= ADSET_MIN_SPEND and roas < CUT_ROAS:
            recs.append(f"⬇️ **{a}** 예산 축소/점검 — 7일 ROAS {roas:.2f} (지출 ₩{w_s[a]:,.0f})")
        if w_p[a] == 0 and w_s[a] >= ZERO_PURCH_SPEND:
            recs.append(f"🚫 **{a}** 소재/타겟 점검 — 7일 구매 0, 지출 ₩{w_s[a]:,.0f}")

    L.append("")
    if recs:
        L.append("**📌 조치 제안** _(검토용 — 자동 실행 안 함)_")
        L.extend(recs)
    else:
        L.append("*📌 조치 제안* — 특이사항 없음")

    L.append("")
    L.append("대시보드: https://meta-ad-noma-dashboard.streamlit.app (비번 nomadia123)")
    print("\n".join(L))


if __name__ == "__main__":
    main()
