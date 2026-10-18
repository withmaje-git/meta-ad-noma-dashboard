"""메타 get_ads 원본 JSON에서 소재(광고) 썸네일을 내려받아 소재 성과 탭용
data/creatives.csv + data/creatives/<ad_id>.jpg 를 생성한다.

사용:
    python scripts/build_creatives.py raw_ads.json [data/insights_daily.csv]

raw_ads.json = meta-ads MCP get_ads(account, fields=
  id,name,status,effective_status,
  creative{object_type,thumbnail_url,image_url,image_hash,
           object_story_spec{video_data{image_url},link_data{picture,image_hash},
                             photo_data{url},template_data{picture}}}) 결과.
({"result":"<json>"} 래퍼든 순수 JSON이든 모두 처리.)

- 성과 CSV에 등장하는 소재(ad_name)만 내려받아 repo 용량을 아낀다.
- 이미지는 facebook ads 풀사이즈(video_data.image_url / creative.image_url 등)를
  우선 쓰고, 없으면 64x64 thumbnail_url 로 폴백한다.
- 같은 이름의 광고가 여러 개면 ACTIVE·풀이미지 우선으로 하나만 쓴다.
"""
import csv
import io
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(HERE, "data", "creatives")
OUT_CSV = os.path.join(HERE, "data", "creatives.csv")
UA = {"User-Agent": "Mozilla/5.0 (compatible; noma-dashboard/1.0)"}
MAX_PX = 512   # 그리드 썸네일용 — 긴 변 이 값으로 축소(용량·로딩 절감)
KEEP_EXISTING = "--refresh-all" not in sys.argv  # 기존 썸네일 재다운로드 생략(기본)

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False


def load_ads(path):
    with open(path, encoding="utf-8") as f:
        obj = json.load(f)
    if isinstance(obj, dict) and isinstance(obj.get("result"), str):
        obj = json.loads(obj["result"])
    return obj.get("data", obj if isinstance(obj, list) else [])


def best_image(cr: dict):
    """(url, quality) 반환. quality: 'full' 이면 풀사이즈, 'thumb' 이면 64x64."""
    oss = cr.get("object_story_spec") or {}
    vd = oss.get("video_data") or {}
    ld = oss.get("link_data") or {}
    pd = oss.get("photo_data") or {}
    td = oss.get("template_data") or {}
    for url in (vd.get("image_url"), cr.get("image_url"), ld.get("picture"),
                pd.get("url"), td.get("picture")):
        if url:
            return url, "full"
    if cr.get("thumbnail_url"):
        return cr["thumbnail_url"], "thumb"
    return None, None


def csv_ad_names(csv_path):
    names = set()
    try:
        with open(csv_path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if float(r.get("spend") or 0) > 0:
                    names.add(r["ad"])
    except FileNotFoundError:
        pass
    return names


def download(url, dest):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    if not data:
        raise ValueError("empty body")
    if _HAS_PIL:
        try:
            im = Image.open(io.BytesIO(data)).convert("RGB")
            # 그리드가 가지런하도록 중앙 정사각 크롭 후 축소
            w, h = im.size
            side = min(w, h)
            im = im.crop(((w - side) // 2, (h - side) // 2,
                          (w + side) // 2, (h + side) // 2))
            if side > MAX_PX:
                im = im.resize((MAX_PX, MAX_PX), Image.LANCZOS)
            im.save(dest, "JPEG", quality=82, optimize=True)
            return os.path.getsize(dest)
        except Exception:
            pass   # 디코드 실패 시 원본 바이트 저장
    with open(dest, "wb") as f:
        f.write(data)
    return len(data)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit("usage: build_creatives.py <raw_ads.json> [insights_csv] [--refresh-all]")
    raw = args[0]
    csv_path = args[1] if len(args) > 1 else os.path.join(HERE, "data", "insights_daily.csv")
    wanted = csv_ad_names(csv_path)
    ads = load_ads(raw)

    # 이름별로 가장 좋은 광고 하나 선택: ACTIVE 우선 → 풀이미지 우선.
    def rank(a):
        cr = a.get("creative") or {}
        _, q = best_image(cr)
        active = 0 if (a.get("effective_status") == "ACTIVE") else 1
        full = 0 if q == "full" else 1
        return (active, full)

    by_name = {}
    for a in ads:
        name = a.get("name")
        if not name:
            continue
        if wanted and name not in wanted:
            continue
        if name not in by_name or rank(a) < rank(by_name[name]):
            by_name[name] = a

    os.makedirs(OUT_DIR, exist_ok=True)
    rows = []
    ok = full_cnt = thumb_cnt = fail = 0
    for name, a in sorted(by_name.items()):
        cr = a.get("creative") or {}
        ad_id = a.get("id") or ""
        url, quality = best_image(cr)
        obj_type = cr.get("object_type") or ""
        is_video = 1 if (obj_type == "VIDEO" or (cr.get("object_story_spec") or {}).get("video_data")) else 0
        fname = f"{ad_id}.jpg"
        dest = os.path.join(OUT_DIR, fname)

        # 이미 받은 소재는 재다운로드 생략(주간 재푸시로 repo 비대해지는 것 방지).
        # 전체 새로고침은 `--refresh-all` 로 강제.
        if KEEP_EXISTING and os.path.exists(dest):
            ok += 1
            rows.append({
                "ad": name, "ad_id": ad_id, "object_type": obj_type,
                "is_video": is_video, "status": a.get("effective_status") or a.get("status") or "",
                "img": f"creatives/{fname}", "quality": "kept",
            })
            continue

        got = False
        # 풀이미지 시도 → 실패 시 thumbnail 폴백
        candidates = [(url, quality)]
        if quality == "full" and cr.get("thumbnail_url"):
            candidates.append((cr["thumbnail_url"], "thumb"))
        for u, q in candidates:
            if not u:
                continue
            try:
                download(u, dest)
                quality = q
                got = True
                break
            except Exception as e:
                print(f"  ! {name[:30]} {q} 실패: {type(e).__name__}")
        if not got:
            fail += 1
            continue
        ok += 1
        full_cnt += quality == "full"
        thumb_cnt += quality == "thumb"
        rows.append({
            "ad": name,
            "ad_id": ad_id,
            "object_type": obj_type,
            "is_video": is_video,
            "status": a.get("effective_status") or a.get("status") or "",
            "img": f"creatives/{fname}",
            "quality": quality,
        })

    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=["ad", "ad_id", "object_type", "is_video", "status", "img", "quality"])
        w.writeheader()
        w.writerows(rows)

    # 이번에 쓰지 않은 오래된 썸네일 제거(폴더를 현재 소재셋과 일치시킴)
    keep = {f"{r['ad_id']}.jpg" for r in rows}
    removed = 0
    for fn in os.listdir(OUT_DIR):
        if fn.endswith(".jpg") and fn not in keep:
            os.remove(os.path.join(OUT_DIR, fn))
            removed += 1
    if removed:
        print(f"removed {removed} stale thumbnails")

    print(f"wrote {len(rows)} creatives -> {OUT_CSV}")
    print(f"downloaded ok={ok} (full={full_cnt}, thumb={thumb_cnt}) fail={fail}")
    if wanted:
        missing = sorted(wanted - set(by_name))
        print(f"성과 CSV 소재 {len(wanted)}개 중 소재이미지 매칭 {len(by_name)}개, 미매칭 {len(missing)}개")
        for m in missing[:10]:
            print("  - 미매칭:", m)


if __name__ == "__main__":
    main()
