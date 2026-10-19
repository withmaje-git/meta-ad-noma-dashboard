"""소재(광고) 리스트 뷰용 메타데이터 CSV(data/creative_meta.csv)를 만든다.

컬럼: ad(소재명), created_date(게시일), product_line(밀크/버블/기타),
      format(영상/이미지), hook_rate(후킹률 %), avg_watch_sec(평균 재생 시간, 초),
      impressions, video_3s(3초 재생수)

사용:
    python scripts/build_creative_meta.py <raw_ads.json> <raw_insights.json> [out_csv]

- raw_ads.json   = meta-ads get_ads(fields=id,name,status,effective_status,
                     created_time,creative{object_type,video_id}) 결과.
- raw_insights.json = meta-ads get_insights(level=ad, time_range=last_90d,
                     fields=[video_play_actions, video_avg_time_watched_actions, ...]) 결과.
  ({"result":"<json>"} 래퍼든 순수 JSON이든 모두 처리.)

지표 정의
  후킹률(hook_rate)   = 3초 동영상 재생(actions.video_view) / 노출 * 100   (영상만)
    * video_play_actions(자동재생 '재생 시작')은 노출의 85~90%라 포화돼 변별력이 없어,
      실제 후킹을 재는 3초 재생(actions 배열의 video_view)을 분자로 쓴다.
  지속시간(avg_watch) = 평균 동영상 재생 시간(video_avg_time_watched_actions, 초)   (영상만)
  * 같은 이름의 광고가 여러 개면 노출·3초재생은 합산, 평균 재생시간은 재생수 가중평균,
    게시일은 가장 이른 생성일로 집계한다(= 대시보드 소재 집계가 이름 단위라 동일하게).
"""
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_CSV = os.path.join(HERE, "data", "creative_meta.csv")


def load(path):
    with open(path, encoding="utf-8") as f:
        obj = json.load(f)
    if isinstance(obj, dict) and isinstance(obj.get("result"), str):
        obj = json.loads(obj["result"])
    return obj.get("data", obj if isinstance(obj, list) else [])


def av(lst, action_type):
    """action 배열에서 특정 action_type 값 추출(없으면 0)."""
    for a in (lst or []):
        if a.get("action_type") == action_type:
            try:
                return float(a.get("value") or 0)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def product_line(name: str) -> str:
    n = name or ""
    if "밀크" in n:
        return "밀크"
    if "버블" in n:
        return "버블"
    return "기타"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        raise SystemExit("usage: build_creative_meta.py <raw_ads.json> <raw_insights.json> [out_csv]")
    raw_ads, raw_ins = args[0], args[1]
    out = args[2] if len(args) > 2 else OUT_CSV

    # ---- 광고 메타: 이름 -> 게시일(최소), 영상여부 ----
    ads = load(raw_ads)
    name_created = {}   # name -> earliest created date (YYYY-MM-DD)
    name_is_video = {}  # name -> bool
    for a in ads:
        name = a.get("name")
        if not name:
            continue
        ct = (a.get("created_time") or "")[:10]
        if ct and (name not in name_created or ct < name_created[name]):
            name_created[name] = ct
        cr = a.get("creative") or {}
        is_vid = (cr.get("object_type") == "VIDEO") or bool(cr.get("video_id"))
        name_is_video[name] = name_is_video.get(name, False) or is_vid

    # ---- 인사이트: 이름 -> 노출/3초재생/평균시청시간 합산 ----
    ins = load(raw_ins)
    agg = {}  # name -> dict
    for m in ins:
        name = m.get("ad_name")
        if not name:
            continue
        imp = float(m.get("impressions") or 0)
        plays3 = av(m.get("actions"), "video_view")                      # 3초 재생
        plays = av(m.get("video_play_actions"), "video_view")            # 재생 시작(가중용)
        avg_t = av(m.get("video_avg_time_watched_actions"), "video_view")
        d = agg.setdefault(name, {"imp": 0.0, "p3": 0.0, "plays": 0.0, "watch_sum": 0.0})
        d["imp"] += imp
        d["p3"] += plays3
        d["plays"] += plays
        d["watch_sum"] += avg_t * plays   # 재생수 가중 -> 총 시청시간 근사

    names = sorted(set(name_created) | set(agg))
    rows = []
    for name in names:
        a = agg.get(name, {"imp": 0.0, "p3": 0.0, "plays": 0.0, "watch_sum": 0.0})
        is_video = name_is_video.get(name, False) or ("영상" in name) or a["plays"] > 0
        hook = (a["p3"] / a["imp"] * 100) if (is_video and a["imp"] > 0) else ""
        avg_watch = (a["watch_sum"] / a["plays"]) if (is_video and a["plays"] > 0) else ""
        rows.append({
            "ad": name,
            "created_date": name_created.get(name, ""),
            "product_line": product_line(name),
            "format": "영상" if is_video else "이미지",
            "hook_rate": round(hook, 1) if hook != "" else "",
            "avg_watch_sec": round(avg_watch, 1) if avg_watch != "" else "",
            "impressions": int(a["imp"]),
            "video_3s": int(a["p3"]),
        })

    with open(out, "w", newline="", encoding="utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=[
            "ad", "created_date", "product_line", "format",
            "hook_rate", "avg_watch_sec", "impressions", "video_3s"])
        w.writeheader()
        w.writerows(rows)

    nv = sum(1 for r in rows if r["format"] == "영상")
    print(f"wrote {len(rows)} creatives -> {out}  (video {nv} / image {len(rows) - nv})")
    mk = sum(1 for r in rows if r["product_line"] == "밀크")
    bb = sum(1 for r in rows if r["product_line"] == "버블")
    print(f"line: milk {mk} / bubble {bb} / etc {len(rows) - mk - bb}")


if __name__ == "__main__":
    main()
