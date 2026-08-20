import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

st.set_page_config(page_title="광고 성과 대시보드", page_icon="🏢", layout="wide")


# ==================== 비밀번호 잠금 ====================
def secret(key, default=None):
    """secrets.toml 이 없어도 에러 없이 기본값 반환 (로컬 실행 대비)."""
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


def check_password():
    pw = secret("app_password", None)
    if not pw:                       # 비번 미설정(로컬 모드) → 통과
        return True
    if st.session_state.get("auth_ok"):
        return True
    st.markdown("### 🔒 광고 성과 대시보드")
    st.caption("관계자에게 전달받은 비밀번호를 입력해 주세요.")
    with st.form("login"):
        entered = st.text_input("비밀번호", type="password", label_visibility="collapsed",
                                placeholder="비밀번호")
        ok = st.form_submit_button("입장")
    if ok:
        if entered == pw:
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")
    return False


if not check_password():
    st.stop()


# ==================== 데이터 로드 ====================
@st.cache_data
def load_data(path: str = "data/insights_daily.csv") -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    return df

df_raw = load_data()

# 최근 14일로 한정
LATEST = df_raw["date"].max()
WINDOW_START = LATEST - pd.Timedelta(days=13)
df_all = df_raw[df_raw["date"] >= WINDOW_START].copy()

# 특정 캠페인 제외(요청): 대시보드 전 구간에서 숨김(총 성과 요약 KPI 포함).
# 우리는 '구매전환' 캠페인만 확인하고, 참여·게시물 부스팅은 별도로 봄.
EXCLUDE_CAMPAIGNS = {"새 판매 캠페인"}
# 참여/게시물 부스팅 캠페인은 이름이 매번 달라지므로 접두어로 제외.
EXCLUDE_PREFIXES = ("참여", "Instagram 게시물")
_excl = df_all["campaign"].isin(EXCLUDE_CAMPAIGNS) | df_all["campaign"].apply(
    lambda c: any(str(c).startswith(p) for p in EXCLUDE_PREFIXES)
)
df_all = df_all[~_excl].copy()

date_min, date_max = df_all["date"].min(), df_all["date"].max()

# ==================== 어제(최신일) 지출 0 항목 제외 ====================
# 캠페인·광고세트·소재 각 레벨에서 최신일 지출이 0이면(=이미 중단) 제외.
def active_names(col: str) -> set:
    return set(df_all[(df_all["date"] == LATEST) & (df_all["spend"] > 0)][col])

ACT_CAMP = active_names("campaign")
ACT_ADSET = active_names("adset")
ACT_AD = active_names("ad")

all_camp = set(df_all["campaign"]); all_adset = set(df_all["adset"]); all_ad = set(df_all["ad"])
excl_camp = sorted(all_camp - ACT_CAMP)
excl_adset = sorted(all_adset - ACT_ADSET)
excl_ad = sorted(all_ad - ACT_AD)

df_camp = df_all[df_all["campaign"].isin(ACT_CAMP)]   # 1단계 & KPI
df_adset = df_all[df_all["adset"].isin(ACT_ADSET)]    # 2단계
df_ad = df_all[df_all["ad"].isin(ACT_AD)]             # 3단계

# ==================== 사이드바 ====================
st.sidebar.header("필터")
MIN_LINE_SPEND = st.sidebar.number_input(
    "선그래프 최소 누적지출(원) — 이하 항목 숨김", min_value=0,
    value=1000, step=1000,
    help="2·3단계 선그래프에서 14일 누적 지출이 이 값 미만인 항목은 잡음이라 숨깁니다.",
)
DAILY_LABEL_MIN = st.sidebar.number_input(
    "ROAS 라벨 표시 최소 일지출(원)", min_value=0, value=5000, step=1000,
    help="선그래프 점 위 ROAS 숫자는 그날 지출이 이 값 이상일 때만 표시합니다.",
)
if excl_camp or excl_adset or excl_ad:
    with st.sidebar.expander(f"제외됨 (어제 지출 0)", expanded=False):
        st.caption(f"캠페인 {len(excl_camp)} · 광고세트 {len(excl_adset)} · 소재 {len(excl_ad)}")
        for x in excl_camp: st.write("· (캠페인) " + x)
        for x in excl_adset: st.write("· (세트) " + x)
        for x in excl_ad: st.write("· (소재) " + x)

# ==================== 헤더 ====================
st.title("🏢 광고 성과 대시보드")
st.caption(
    f"기간: {date_min:%Y-%m-%d} ~ {date_max:%Y-%m-%d} (최근 14일)  ·  "
    f"결과=omni_purchase 기준  ·  "
    f"어제({LATEST:%m-%d}) 지출 0인 캠페인·세트·소재는 제외"
)

# ==================== 즉시 조치 요약 ====================
def build_recos(d: pd.DataFrame):
    """최근 7일 & 어제 기준 광고세트별 룰 기반 조치 제안.
    어제(최신일) 지출 0인 세트는 이미 조치한 것으로 보고 제외."""
    last7_start = LATEST - pd.Timedelta(days=6)
    d7 = d[d["date"] >= last7_start]
    reds, greens, yellows = [], [], []
    for adset in sorted(d["adset"].unique()):
        ay = d[(d["adset"] == adset) & (d["date"] == LATEST)]
        sy = ay["spend"].sum()
        if sy <= 0:            # 어제 지출 0 → 이미 조치, 제외
            continue
        a7 = d7[d7["adset"] == adset]
        s7 = a7["spend"].sum()
        v7 = a7["purchase_value"].sum()
        r7 = v7 / s7 if s7 else 0
        py = int(ay["purchase"].sum())
        if s7 >= 100000 and r7 < 1.0:
            reds.append(
                f"**{adset}** — 최근 7일 ROAS **{r7:.2f}** 적자 "
                f"(지출 ₩{s7:,.0f} → 매출 ₩{v7:,.0f}). "
                f"어제도 ₩{sy:,.0f} 쓰고 구매 {py}건 → **중단 또는 소재/타겟 교체** 검토."
            )
        elif r7 >= 2.5:
            greens.append(
                f"**{adset}** — 최근 7일 ROAS **{r7:.2f}** 우수 "
                f"(지출 ₩{s7:,.0f}). **예산 증액** 여지."
            )
        elif py == 0 and sy >= 20000:
            yellows.append(
                f"**{adset}** — 어제 ₩{sy:,.0f} 집행했으나 구매 0건 "
                f"(최근 7일 ROAS {r7:.2f}) → **오늘 관찰**, 지속 시 소재 점검."
            )
        elif r7 < 1.0 and s7 > 0:
            yellows.append(
                f"**{adset}** — 최근 7일 ROAS **{r7:.2f}** 손익분기 미만 "
                f"(지출 ₩{s7:,.0f}). 소액이라 관찰 권장."
            )
    return reds, greens, yellows

reds, greens, yellows = build_recos(df_camp)

st.subheader("⚡ 지금 바로 조치하면 좋을 것")
st.caption("최근 7일·어제 실적 기준 자동 제안. 어제 지출이 0인(이미 중단한) 광고세트는 제외했습니다.")
if not (reds or greens or yellows):
    st.success("특별한 조치가 필요한 광고세트가 없습니다. 현 상태 유지하세요.")
else:
    for r in reds:
        st.error("🔴 " + r)
    for y in yellows:
        st.warning("🟡 " + y)
    for g in greens:
        st.success("🟢 " + g)

st.divider()

# ==================== KPI ====================
tot_spend = df_camp["spend"].sum()
tot_purch = df_camp["purchase"].sum()
tot_pval = df_camp["purchase_value"].sum()
roas = tot_pval / tot_spend if tot_spend else 0
cpp = tot_spend / tot_purch if tot_purch else 0
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("총 지출", f"₩{tot_spend:,.0f}")
c2.metric("구매", f"{tot_purch:,.0f} 건")
c3.metric("구매 전환값", f"₩{tot_pval:,.0f}")
c4.metric("ROAS", f"{roas:.2f}")
c5.metric("구매당 비용", f"₩{cpp:,.0f}" if cpp else "—")

st.divider()

PALETTE = px.colors.qualitative.Plotly + px.colors.qualitative.Set2 + px.colors.qualitative.Dark24


def daily_spend_roas(d: pd.DataFrame, group_col: str) -> pd.DataFrame:
    g = d.groupby(["date", group_col]).agg(
        spend=("spend", "sum"), purchase_value=("purchase_value", "sum"),
    ).reset_index()
    g["roas"] = (g["purchase_value"] / g["spend"]).where(g["spend"] > 0, 0)
    return g


def add_rolling_roas(g: pd.DataFrame, window: int = 7) -> pd.DataFrame:
    """일별 집계(g: date/spend/purchase_value)에 최근 window일 누적 ROAS(roas7) 추가.
    달력상 빠진 날짜가 있어도 정확하도록 일단위로 reindex 후 롤링합계."""
    g = g.sort_values("date").copy()
    full = pd.date_range(g["date"].min(), g["date"].max(), freq="D")
    daily = g.set_index("date")[["spend", "purchase_value"]].reindex(full).fillna(0)
    rs = daily["spend"].rolling(window, min_periods=1).sum()
    rv = daily["purchase_value"].rolling(window, min_periods=1).sum()
    roas7 = (rv / rs).where(rs > 0, 0)
    roas7.index.name = "date"
    return g.merge(roas7.rename("roas7").reset_index(), on="date", how="left")


def dual_axis_chart(g: pd.DataFrame):
    """지출 막대 + 당일 ROAS 선(점 위 숫자) + 최근 7일 ROAS 선 이중축 그래프."""
    g = add_rolling_roas(g.sort_values("date"))
    labels = [f"{r:.1f}" if s > 0 else "" for s, r in zip(g["spend"], g["roas"])]
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(x=g["date"], y=g["spend"], name="지출(파랑)",
               marker_color="#3b82f6", opacity=0.75,
               hovertemplate="지출 ₩%{y:,.0f}<extra></extra>"),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(x=g["date"], y=g["roas"], name="당일 ROAS(주황)",
                   mode="lines+markers+text", line=dict(color="#f59e0b", width=3),
                   marker=dict(size=7), text=labels, textposition="top center",
                   textfont=dict(size=11, color="#b45309"),
                   hovertemplate="당일 ROAS %{y:.2f}<extra></extra>"),
        secondary_y=True,
    )
    fig.add_trace(
        go.Scatter(x=g["date"], y=g["roas7"], name="최근 7일 ROAS(보라)",
                   mode="lines+markers", line=dict(color="#7c3aed", width=2.5, dash="dash"),
                   marker=dict(size=5),
                   hovertemplate="최근 7일 ROAS %{y:.2f}<extra></extra>"),
        secondary_y=True,
    )
    fig.add_hline(y=1.0, line_dash="dot", line_color="gray", secondary_y=True)
    fig.update_layout(
        height=330, hovermode="x unified", margin=dict(t=44, b=0),
        legend=dict(orientation="h", x=0.5, xanchor="center", y=1.02, yanchor="bottom"),
    )
    fig.update_yaxes(title_text="지출(원)", secondary_y=False, rangemode="tozero")
    fig.update_yaxes(title_text="ROAS", secondary_y=True, rangemode="tozero")
    st.plotly_chart(fig, width="stretch")


def multiline_spend_with_roas(g: pd.DataFrame, series_col: str):
    """한 그래프에 시리즈별 지출 선 + 점 위 ROAS 라벨. 범례는 하단 가운데 정렬."""
    totals = g.groupby(series_col)["spend"].sum()
    series = list(totals[totals >= MIN_LINE_SPEND].sort_values(ascending=False).index)
    if not series:
        st.info("표시할 항목이 없습니다. (사이드바의 '최소 누적지출' 값을 낮춰보세요.)")
        return
    fig = go.Figure()
    for i, name in enumerate(series):
        gg = g[g[series_col] == name].sort_values("date")
        color = PALETTE[i % len(PALETTE)]
        labels = [f"{r:.1f}" if s >= DAILY_LABEL_MIN else ""
                  for s, r in zip(gg["spend"], gg["roas"])]
        fig.add_trace(go.Scatter(
            x=gg["date"], y=gg["spend"], name=name,
            mode="lines+markers+text", line=dict(color=color, width=2),
            marker=dict(size=6), text=labels, textposition="top center",
            textfont=dict(size=10, color=color), customdata=gg["roas"],
            hovertemplate="지출 ₩%{y:,.0f} · ROAS %{customdata:.1f}<extra>" + str(name) + "</extra>",
        ))
    fig.update_layout(
        height=440, hovermode="closest", margin=dict(t=30, b=0),
        legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.22, yanchor="top"),
    )
    fig.update_yaxes(title_text="지출(원)", rangemode="tozero")
    fig.update_xaxes(title_text="날짜")
    st.plotly_chart(fig, width="stretch")


# ==================== 1단계: 캠페인별 (캠페인마다 이중축) ====================
st.header("① 캠페인별 — 지출(막대) & ROAS(선)")
st.caption("구매전환 캠페인마다 개별 그래프. 파란 막대=일별 지출(왼쪽 축), "
           "주황 선=그날 ROAS, 보라 점선=그날 기준 최근 7일 ROAS(오른쪽 축). "
           "회색 점선=ROAS 1.0(본전).")

camp_only = (
    df_camp.groupby("campaign")["spend"].sum().sort_index().index.tolist()
)
for camp in camp_only:
    cdf = df_camp[df_camp["campaign"] == camp]
    g = cdf.groupby("date").agg(
        spend=("spend", "sum"), purchase_value=("purchase_value", "sum"),
    ).reset_index()
    if g["spend"].sum() <= 0:
        continue
    g["roas"] = (g["purchase_value"] / g["spend"]).where(g["spend"] > 0, 0)
    c_spend = g["spend"].sum(); c_val = g["purchase_value"].sum()
    c_roas = c_val / c_spend if c_spend else 0
    st.markdown(f"**📁 {camp}**  ·  지출 ₩{c_spend:,.0f} · ROAS {c_roas:.2f}")
    dual_axis_chart(g)
st.divider()

# ==================== 2단계: 캠페인 · 광고세트별 (각 세트마다 이중축) ====================
st.header("② 캠페인 · 광고세트별 — 지출(막대) & ROAS(선)")
st.caption("캠페인 아래 광고세트마다 개별 그래프. 파란 막대=일별 지출(왼쪽 축), "
           "주황 선=그날 ROAS, 보라 점선=그날 기준 최근 7일 ROAS(오른쪽 축). "
           "점 위 숫자=그날 ROAS(소수점 1자리). 회색 점선=ROAS 1.0(본전).")

campaigns = (
    df_adset.groupby("campaign")["spend"].sum().sort_index().index.tolist()
)
for camp in campaigns:
    cdf = df_adset[df_adset["campaign"] == camp]
    c_spend = cdf["spend"].sum(); c_val = cdf["purchase_value"].sum()
    c_roas = c_val / c_spend if c_spend else 0
    st.subheader(f"📁 {camp}")
    st.caption(f"캠페인 합계 · 지출 ₩{c_spend:,.0f} · ROAS {c_roas:.2f}")
    adsets_in = cdf.groupby("adset")["spend"].sum().sort_index().index
    for aset in adsets_in:
        g = cdf[cdf["adset"] == aset].groupby("date").agg(
            spend=("spend", "sum"), purchase_value=("purchase_value", "sum"),
        ).reset_index()
        if g["spend"].sum() <= 0:
            continue
        g["roas"] = (g["purchase_value"] / g["spend"]).where(g["spend"] > 0, 0)
        a_spend = g["spend"].sum(); a_val = g["purchase_value"].sum()
        a_roas = a_val / a_spend if a_spend else 0
        st.markdown(f"**{aset}**  ·  지출 ₩{a_spend:,.0f} · ROAS {a_roas:.2f}")
        dual_axis_chart(g)
    st.divider()

# ==================== 3단계: 소재별 (광고세트별로 분리한 다중 선) ====================
st.header("③ 소재별 — 광고세트별로 분리 (지출 선 + ROAS 라벨)")
st.caption("광고세트마다 그 안의 소재별 일별 지출 선. 점 위 숫자=그날 ROAS(소수점 1자리). "
           "범례(소재명)는 그래프 아래 가운데에 표시됩니다.")

ad_adsets = (
    df_ad.groupby("adset")["spend"].sum().sort_index().index.tolist()
)
for aset in ad_adsets:
    sub = df_ad[df_ad["adset"] == aset]
    a_spend = sub["spend"].sum(); a_val = sub["purchase_value"].sum()
    a_roas = a_val / a_spend if a_spend else 0
    st.markdown(f"**{aset}**  ·  지출 ₩{a_spend:,.0f} · ROAS {a_roas:.2f}")
    multiline_spend_with_roas(daily_spend_roas(sub, "ad"), "ad")
    st.divider()

st.caption(
    "데이터는 스냅샷(CSV)입니다. 갱신하려면 meta-ads MCP get_insights(level=ad, "
    "time_breakdown=day, 최근 14일)를 다시 뽑아 data/insights_daily.csv를 재생성하세요. "
    "어트리뷰션 기본 창(클릭 7일/조회 1일)."
)
