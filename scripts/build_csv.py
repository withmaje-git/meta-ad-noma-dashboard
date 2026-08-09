"""MCP get_insights 원본 JSON을 대시보드용 CSV(data/insights_daily.csv)로 변환.

사용:
    python scripts/build_csv.py <raw_insights_json> [out_csv]

<raw_insights_json>은 meta-ads MCP get_insights(level=ad, time_breakdown=day)의
결과 파일. {"result": "<json문자열>"} 래퍼 형태든, 직접 insights JSON이든 모두 처리.
"""
import json
import csv
import sys


def load_insights(path: str):
    with open(path, encoding="utf-8") as f:
        obj = json.load(f)
    # {"result": "<json string>"} 래퍼면 안쪽을 파싱
    if isinstance(obj, dict) and isinstance(obj.get("result"), str):
        obj = json.loads(obj["result"])
    return obj


def action_value(lst, action_type: str):
    for a in (lst or []):
        if a.get("action_type") == action_type:
            return a.get("value")
    return None


def rows_from(obj):
    if "segmented_metrics" in obj:            # time_breakdown=day
        items = [(s["period"], s["metrics"]) for s in obj["segmented_metrics"]]
    elif "data" in obj:                        # 일자 분해 없는 경우
        items = [(m.get("date_start"), m) for m in obj["data"]]
    else:
        raise SystemExit("인식할 수 없는 insights JSON 구조입니다.")

    rows = []
    for date, m in items:
        a = m.get("actions")
        vv = m.get("action_values")
        rows.append({
            "date": date,
            "campaign": m.get("campaign_name"),
            "adset": m.get("adset_name"),
            "ad": m.get("ad_name"),
            "spend": round(float(m.get("spend") or 0)),
            "reach": int(m.get("reach") or 0),
            "impressions": int(m.get("impressions") or 0),
            "clicks": int(m.get("clicks") or 0),
            "link_click": int(action_value(a, "link_click") or 0),
            "purchase": int(action_value(a, "omni_purchase") or 0),
            "purchase_value": round(float(action_value(vv, "omni_purchase") or 0)),
            "frequency": round(float(m.get("frequency") or 0), 3),
            "cpc": round(float(m.get("cpc") or 0)) if m.get("cpc") else 0,
            "cpm": round(float(m.get("cpm") or 0)) if m.get("cpm") else 0,
            "ctr": round(float(m.get("ctr") or 0), 3) if m.get("ctr") else 0,
        })
    rows.sort(key=lambda r: (r["adset"] or "", r["ad"] or "", r["date"] or ""))
    return rows


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: build_csv.py <raw_insights_json> [out_csv]")
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "data/insights_daily.csv"
    rows = rows_from(load_insights(src))
    if not rows:
        raise SystemExit("행이 0개입니다 — 원본 JSON을 확인하세요.")
    with open(out, "w", newline="", encoding="utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    tot_spend = sum(r["spend"] for r in rows)
    tot_pv = sum(r["purchase_value"] for r in rows)
    roas = tot_pv / tot_spend if tot_spend else 0
    print(f"wrote {len(rows)} rows -> {out}")
    print(f"spend={tot_spend:,} purchase={sum(r['purchase'] for r in rows)} "
          f"value={tot_pv:,} roas={roas:.3f}")


if __name__ == "__main__":
    main()
