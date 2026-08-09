# 광고 성과 대시보드

Meta(페이스북) 광고 **소재별 일별 성과**를 보는 Streamlit 대시보드입니다.

- 데이터: 스냅샷 CSV (`data/insights_daily.csv`)
- 기능: KPI 카드, 소재별 일별 추이(지표 선택), 광고세트별 일별 지출, 소재 요약표, 광고세트/소재 필터

## 폴더 구조
```
ad-dashboard/
├─ app.py                    # Streamlit 앱
├─ requirements.txt          # 의존성
├─ data/
│  └─ insights_daily.csv     # 일별 스냅샷 데이터
├─ .gitignore
└─ README.md
```

## 로컬 실행
```bash
pip install -r requirements.txt
streamlit run app.py
```
브라우저에서 http://localhost:8501 열림.

## Streamlit Community Cloud 배포

1. **GitHub에 올리기** (아래 "GitHub 올리기" 참고)
2. https://share.streamlit.io 접속 → GitHub 계정으로 로그인
3. **"Create app" → "Deploy a public app from GitHub"**
4. 설정:
   - Repository: `본인계정/ad-dashboard`
   - Branch: `main`
   - Main file path: `app.py`
5. **Deploy** 클릭 → 1~2분 후 `https://<앱이름>.streamlit.app` URL 생성

> 이 앱은 **공용 비밀번호 게이트**로 화면을 보호합니다(app.py의 `check_password()`).
> Streamlit Cloud 앱 Settings → Secrets 에 `app_password = "..."` 를 넣으면 잠금이 켜지고,
> 없으면(로컬) 잠금 없이 열립니다. Public 배포 시에도 비번을 모르면 데이터가 안 보입니다.
> 단, **repo 가 public 이면 `data/insights_daily.csv` 원본은 GitHub 에서 그대로 열람**되니 유의하세요.

## GitHub 올리기 (git CLI)
```bash
cd ad-dashboard
git init
git add .
git commit -m "광고 성과 대시보드"
# GitHub에서 빈 저장소 ad-dashboard 생성 후:
git remote add origin https://github.com/<본인계정>/ad-dashboard.git
git branch -M main
git push -u origin main
```
> GitHub Desktop 앱을 쓰면 이 폴더를 "Add existing repository"로 추가 후 Publish 버튼으로도 가능합니다.

## 데이터 갱신 방법
현재 데이터는 **스냅샷**입니다(최근 7일: 2026-06-26 ~ 07-03).
최신 데이터로 바꾸려면:

1. Claude에게 "최근 N일 광고 데이터 다시 뽑아서 CSV 갱신해줘" 라고 요청
   → Claude가 meta-ads MCP로 새로 뽑아 `data/insights_daily.csv`를 덮어씀
2. 변경된 CSV를 GitHub에 push
   ```bash
   git add data/insights_daily.csv
   git commit -m "데이터 갱신 <날짜>"
   git push
   ```
   → Streamlit Cloud가 자동으로 재배포

> 자동 갱신(매일 아침 등)을 원하면 Claude에게 예약 작업(routine) 설정을 요청하세요.

## CSV 컬럼 정의
| 컬럼 | 의미 |
|---|---|
| date | 날짜 |
| campaign / adset / ad | 캠페인 / 광고세트 / 소재(광고) 이름 |
| spend | 지출(원) |
| reach / impressions / clicks | 도달 / 노출 / 클릭 |
| link_click | 링크 클릭 |
| purchase | 구매 건수 (omni_purchase) |
| purchase_value | 구매 전환값(원) |
| frequency / cpc / cpm / ctr | 빈도 / 링크클릭당비용 / 1000노출당비용 / 클릭률 |

> 지표 기준: 결과 = `omni_purchase`(구매), 어트리뷰션 기본 창(클릭 7일 / 조회 1일).
