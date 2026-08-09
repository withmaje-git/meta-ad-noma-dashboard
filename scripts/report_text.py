"""data/insights_daily.csv에서 슬랙용 일일 리포트 '문구'를 만들어 stdout에 출력.

전송은 하지 않는다(클라우드 루틴이 Slack 커넥터로 DM 전송).
포맷은 펫햄프(PETHEMP) 리포트와 동일:
  ① 계정 전체 최근 7일 합계
  ② 계정 전체 어제 vs 7일 일평균
  ③ 광고세트별 어제 vs 7일 일평균 (어제 지출>0 세트만, 어제 지출 desc)
  ④ 지금 바로 조치하면 좋을 것
'새 판매 캠페인'은 리포트에서 제외.
"""
import os
import csv
from collections import defaultdict

CSV_PATH = os.environ.get("CSV_PATH", "data/insights_daily.csv")
EXCLUDE_CAMPAIGNS = {"새 판매 캠페인"}

# 조치 제안 임계값 (펫햄프/클라리온과 동일)
RED_SPEND = 100000   # 7일 지출 이 이상 + ROAS<1 → 중단/교체
GREEN_ROAS = 2.5     # 7일 ROAS 이 이상 → 증액
YELLOW_ZERO_SPEND = 20000  # 어제 구매 0인데 어제 지출 이 이상 → 관찰


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def pct(a, avg):
    return (a - avg) / avg * 100 if avg else 0.0


def main():
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r["campaign"] not in EXCLUDE_CAMPAIGNS]
    if not rows:
        print("CSV가 비어 있습니다.")
        return

    dates = sorted({r["date"] for r in rows})
    latest = dates[-1]
    last7 = dates[-7:]
    ndays = len(last7)
    last7set = set(last7)

    # ── 계정 전체 집계 ──
    def acc(pred):
        s = v = p = 0.0
        for r in rows:
            if pred(r):
                s += num(r["spend"]); v += num(r["purchase_value"]); p += num(r["purchase"])
        return s, v, p

    s7, v7, p7 = acc(lambda r: r["date"] in last7set)
    sy, vy, py = acc(lambda r: r["date"] == latest)
    roas7 = v7 / s7 if s7 else 0
    roasy = vy / sy if sy else 0
    avg_s, avg_v, avg_p = (s7 / ndays, v7 / ndays, p7 / ndays) if ndays else (0, 0, 0)
    cpa_y = (sy / py) if py else None

    L = []
    L.append(f"🧴 **노마디아 광고 리포트** · {latest} 기준")
    L.append("")
    L.append(f"📊 **계정 전체 · 최근 7일 합계** ({last7[0]}~{last7[-1]})")
    L.append(f"· 지출: ₩{s7:,.0f}")
    L.append(f"· 구매: {p7:.0f}건")
    L.append(f"· 매출: ₩{v7:,.0f}")
    L.append(f"· ROAS: {roas7:.2f}")
    L.append("")
    L.append(f"📅 **계정 전체 · 어제({latest}) vs 7일 일평균**")
    L.append(f"· 지출: ₩{sy:,.0f} (일평균 ₩{avg_s:,.0f} 대비 {pct(sy, avg_s):+.2f}%)")
    L.append(f"· 구매: {py:.0f}건 (일평균 {avg_p:.1f}건)")
    L.append(f"· 매출: ₩{vy:,.0f} (일평균 ₩{avg_v:,.0f} 대비 {pct(vy, avg_v):+.2f}%)")
    L.append(f"· ROAS: 어제 {roasy:.2f} (7일 {roas7:.2f})")
    L.append(f"· CPA: ₩{cpa_y:,.0f}" if cpa_y else "· CPA: N/A (어제 구매 0건)")

    # ── 광고세트별 ──
    ays = defaultdict(float); ayp = defaultdict(float); ayv = defaultdict(float)   # 어제
    a7s = defaultdict(float); a7p = defaultdict(float); a7v = defaultdict(float)   # 7일
    for r in rows:
        a = r["adset"]
        if r["date"] == latest:
            ays[a] += num(r["spend"]); ayp[a] += num(r["purchase"]); ayv[a] += num(r["purchase_value"])
        if r["date"] in last7set:
            a7s[a] += num(r["spend"]); a7p[a] += num(r["purchase"]); a7v[a] += num(r["purchase_value"])

    active = sorted([a for a in ays if ays[a] > 0], key=lambda x: -ays[x])   # 어제 지출 desc
    L.append("")
    L.append("📦 **광고세트별 · 어제 vs 최근 7일 일평균** (어제 지출>0 세트만)")
    for a in active:
        avs = a7s[a] / ndays; avp = a7p[a] / ndays; avv = a7v[a] / ndays
        r7 = a7v[a] / a7s[a] if a7s[a] else 0
        ry = ayv[a] / ays[a] if ays[a] else 0
        L.append(f"• {a}")
        L.append(f"· 지출 ₩{ays[a]:,.0f} (일평균 ₩{avs:,.0f} 대비 {pct(ays[a], avs):+.2f}%)")
        L.append(f"· 구매 {ayp[a]:.0f}건 (일평균 {avp:.1f}건)")
        L.append(f"· 매출 ₩{ayv[a]:,.0f} (일평균 ₩{avv:,.0f} 대비 {pct(ayv[a], avv):+.2f}%)")
        L.append(f"· ROAS {ry:.2f} (7일 {r7:.2f})")

    # ── 조치 제안 (어제 지출>0 세트만) ──
    recs = []
    for a in sorted(a7s, key=lambda x: -a7s[x]):
        if ays.get(a, 0) <= 0:
            continue
        r7 = a7v[a] / a7s[a] if a7s[a] else 0
        if a7s[a] >= RED_SPEND and r7 < 1.0:
            recs.append(f"🔴 {a} — 중단/교체 검토 (7일 ROAS {r7:.2f}, 7일 지출 ₩{a7s[a]:,.0f})")
        elif r7 >= GREEN_ROAS:
            recs.append(f"🟢 증액: {a} — 최근 7일 ROAS {r7:.2f}, 지출 ₩{a7s[a]:,.0f} (조치는 제안일 뿐, 자동 실행 없음)")
        elif ayp.get(a, 0) == 0 and ays[a] >= YELLOW_ZERO_SPEND:
            recs.append(f"🟡 {a} — 관찰 필요: 구매 0건 (어제지출 ₩{ays[a]:,.0f}, 7일 ROAS {r7:.2f})")
        elif r7 < 1.0 and a7s[a] > 0:
            recs.append(f"🟡 {a} — 관찰 권장: 최근 7일 ROAS {r7:.2f} 손익분기 미만 (지출 ₩{a7s[a]:,.0f}, 소액)")

    L.append("")
    L.append("⚡ **지금 바로 조치하면 좋을 것**")
    if recs:
        L.extend(recs)
    else:
        L.append("특별한 조치가 필요한 광고세트가 없습니다. 현 상태 유지하세요.")
    L.append("")
    L.append("※ 조치는 제안일 뿐이며 자동 실행되지 않았습니다. 광고 상태/예산 변경은 직접 검토 후 진행해 주세요.")

    print("\n".join(L))


if __name__ == "__main__":
    main()
