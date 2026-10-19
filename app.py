import os

import pandas as pd
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
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


@st.cache_data
def load_creatives(path: str = "data/creatives.csv") -> pd.DataFrame:
    cols = ["ad", "ad_id", "object_type", "is_video", "status", "img", "quality"]
    try:
        c = pd.read_csv(path)
    except FileNotFoundError:
        return pd.DataFrame(columns=cols)
    return c


@st.cache_data
def load_creative_meta(path: str = "data/creative_meta.csv") -> pd.DataFrame:
    """소재 리스트 뷰용 메타데이터: 게시일·제품라인(밀크/버블)·포맷(영상/이미지)·
    후킹률·지속시간. scripts/build_creative_meta.py 로 생성(최근 90일 기준, 소재 고유값)."""
    cols = ["ad", "created_date", "product_line", "format",
            "hook_rate", "avg_watch_sec", "impressions", "video_3s"]
    try:
        m = pd.read_csv(path)
    except FileNotFoundError:
        return pd.DataFrame(columns=cols)
    return m


df_raw = load_data()
creatives = load_creatives()
cmeta = load_creative_meta()

LATEST = df_raw["date"].max()

# 캠페인 제외 규칙: "어제(최신일) 지출이 0인 캠페인은 전 구간에서 무시".
# 참여·게시물 부스팅·종료된 캠페인 등은 어제 지출이 0이라 자동으로 빠지고,
# 어제도 돌고 있는(지출>0) 캠페인만 개요·그래프·조치에 반영한다. 수동 제외 리스트 없음.
ACTIVE_CAMPAIGNS = set(
    df_raw[(df_raw["date"] == df_raw["date"].max()) & (df_raw["spend"] > 0)]["campaign"]
)


def apply_exclude(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["campaign"].isin(ACTIVE_CAMPAIGNS)].copy()


# 전 기간(최대 28일치) — 개요용
df_incl = apply_exclude(df_raw)

# 그래프용 14일 창
GRAPH_DAYS = 14
WINDOW_START = LATEST - pd.Timedelta(days=GRAPH_DAYS - 1)
df_all = df_incl[df_incl["date"] >= WINDOW_START].copy()
date_min, date_max = df_all["date"].min(), df_all["date"].max()

# 그래프 가로축을 모든 그래프에서 동일하게 맞추기 위한 공통 x 범위
X_RANGE = (WINDOW_START, LATEST)


# ==================== 어제(최신일) 지출 0 항목 제외 ====================
# 캠페인·광고세트·소재 각 레벨에서 최신일 지출이 0이면(=이미 중단) 그래프에서 제외.
def active_names(col: str) -> set:
    return set(df_all[(df_all["date"] == LATEST) & (df_all["spend"] > 0)][col])


ACT_CAMP = active_names("campaign")
ACT_ADSET = active_names("adset")
ACT_AD = active_names("ad")

all_camp = set(df_all["campaign"]); all_adset = set(df_all["adset"]); all_ad = set(df_all["ad"])
excl_camp = sorted(all_camp - ACT_CAMP)
excl_adset = sorted(all_adset - ACT_ADSET)
excl_ad = sorted(all_ad - ACT_AD)

df_camp = df_all[df_all["campaign"].isin(ACT_CAMP)]   # 캠페인 그래프 & 즉시조치
df_adset = df_all[df_all["adset"].isin(ACT_ADSET)]    # 광고세트 그래프
df_ad = df_all[df_all["ad"].isin(ACT_AD)]             # 소재 그래프

# ==================== 사이드바 ====================
st.sidebar.header("필터")
MIN_LINE_SPEND = st.sidebar.number_input(
    "소재 선그래프 최소 누적지출(원) — 이하 소재 숨김", min_value=0,
    value=1000, step=1000,
    help="소재 선그래프에서 14일 누적 지출이 이 값 미만인 소재는 잡음이라 숨깁니다.",
)
DAILY_LABEL_MIN = st.sidebar.number_input(
    "당일 ROAS 라벨 표시 최소 일지출(원)", min_value=0, value=5000, step=1000,
    help="캠페인·광고세트 그래프의 점 위 당일 ROAS 숫자는 그날 지출이 이 값 이상일 때만 표시합니다.",
)
if excl_camp or excl_adset or excl_ad:
    with st.sidebar.expander(f"제외됨 (어제 지출 0)", expanded=False):
        st.caption(f"캠페인 {len(excl_camp)} · 광고세트 {len(excl_adset)} · 소재 {len(excl_ad)}")
        for x in excl_camp: st.write("· (캠페인) " + x)
        for x in excl_adset: st.write("· (세트) " + x)
        for x in excl_ad: st.write("· (소재) " + x)


# ==================== 공용 헬퍼 ====================
PALETTE = px.colors.qualitative.Plotly + px.colors.qualitative.Set2 + px.colors.qualitative.Dark24


def period_metrics(n: int) -> dict:
    start = LATEST - pd.Timedelta(days=n - 1)
    d = df_incl[df_incl["date"] >= start]
    s = d["spend"].sum(); p = int(d["purchase"].sum()); v = d["purchase_value"].sum()
    r = v / s if s else 0
    cpp = s / p if p else 0
    return {
        "총 지출": f"₩{s:,.0f}",
        "구매": f"{p:,d} 건",
        "구매 전환값": f"₩{v:,.0f}",
        "ROAS": f"{r:.2f}",
        "구매당 비용": f"₩{cpp:,.0f}" if p else "—",
    }


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


def _apply_xrange(fig):
    """모든 그래프의 가로축을 동일한 14일 창으로 고정(빠진 날짜는 비워둠)."""
    fig.update_xaxes(range=[X_RANGE[0] - pd.Timedelta(hours=12),
                            X_RANGE[1] + pd.Timedelta(hours=12)])


def dual_axis_chart(g: pd.DataFrame):
    """지출 막대 + 당일 ROAS 선(점 위 숫자) + 최근 7일 ROAS 선(마지막 날 숫자) 이중축."""
    g = add_rolling_roas(g.sort_values("date"))
    # 당일 ROAS 라벨(주황): 그날 지출이 라벨 임계 이상일 때만
    daily_labels = [f"{r:.1f}" if s >= DAILY_LABEL_MIN else ""
                    for s, r in zip(g["spend"], g["roas"])]
    # 최근 7일 ROAS 라벨(보라): 마지막 날 하나만
    roas7_labels = ["" for _ in range(len(g))]
    if len(g):
        lv = g["roas7"].iloc[-1]
        if lv and lv > 0:
            roas7_labels[-1] = f"{lv:.1f}"

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
                   marker=dict(size=7), text=daily_labels, textposition="top center",
                   textfont=dict(size=11, color="#b45309"), cliponaxis=False,
                   hovertemplate="당일 ROAS %{y:.2f}<extra></extra>"),
        secondary_y=True,
    )
    fig.add_trace(
        go.Scatter(x=g["date"], y=g["roas7"], name="최근 7일 ROAS(보라)",
                   mode="lines+markers+text", line=dict(color="#7c3aed", width=2.5, dash="dash"),
                   marker=dict(size=5), text=roas7_labels, textposition="bottom center",
                   textfont=dict(size=12, color="#7c3aed"), cliponaxis=False,
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
    _apply_xrange(fig)
    st.plotly_chart(fig, width="stretch")


def multiline_spend_with_roas(g: pd.DataFrame, series_col: str):
    """한 그래프에 소재별 지출 선. ROAS(≥0.1)는 겹친 선들보다 위에 소재 색으로 표기."""
    totals = g.groupby(series_col)["spend"].sum()
    series = list(totals[totals >= MIN_LINE_SPEND].sort_values(ascending=False).index)
    if not series:
        st.info("표시할 소재가 없습니다. (사이드바의 '최소 누적지출' 값을 낮춰보세요.)")
        return
    color_map = {name: PALETTE[i % len(PALETTE)] for i, name in enumerate(series)}

    fig = go.Figure()
    ymax = 0.0
    gsel = g[g[series_col].isin(series)]
    for name in series:
        gg = gsel[gsel[series_col] == name].sort_values("date")
        if len(gg):
            ymax = max(ymax, float(gg["spend"].max()))
        fig.add_trace(go.Scatter(
            x=gg["date"], y=gg["spend"], name=name,
            mode="lines+markers", line=dict(color=color_map[name], width=2),
            marker=dict(size=6), customdata=gg["roas"],
            hovertemplate="지출 ₩%{y:,.0f} · ROAS %{customdata:.1f}<extra>" + str(name) + "</extra>",
        ))

    # ROAS 라벨: 구매 발생(ROAS≥0.1)한 소재를, 그날 최고 지출선보다 위에 계단식으로 배치.
    ymax = ymax or 1.0
    gap = ymax * 0.09
    day_base = gsel.groupby("date")["spend"].max()
    labeled = gsel[gsel["roas"] >= 0.1]
    top_needed = ymax
    for date, grp in labeled.groupby("date"):
        base = float(day_base.get(date, 0.0))
        grp = grp.sort_values("roas")   # 아래→위 오름차순으로 쌓기
        for k, (_, row) in enumerate(grp.iterrows()):
            y = base + gap * (k + 1)
            top_needed = max(top_needed, y)
            fig.add_trace(go.Scatter(
                x=[date], y=[y], mode="text", text=[f"{row['roas']:.1f}"],
                textposition="middle center", cliponaxis=False, showlegend=False,
                hoverinfo="skip", textfont=dict(size=12, color=color_map[row[series_col]]),
            ))

    fig.update_layout(
        height=460, hovermode="closest", margin=dict(t=30, b=0),
        legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.22, yanchor="top"),
    )
    fig.update_yaxes(title_text="지출(원)", range=[0, top_needed * 1.08])
    fig.update_xaxes(title_text="날짜")
    _apply_xrange(fig)
    st.plotly_chart(fig, width="stretch")


def adset_action_line(sub: pd.DataFrame) -> str:
    """광고세트 하나의 최근 7일·어제 실적으로 한 줄 조치사항 생성."""
    last7 = sub[sub["date"] >= LATEST - pd.Timedelta(days=6)]
    s7 = last7["spend"].sum(); v7 = last7["purchase_value"].sum()
    r7 = v7 / s7 if s7 else 0
    ay = sub[sub["date"] == LATEST]
    sy = ay["spend"].sum(); py = int(ay["purchase"].sum())
    if s7 >= 100000 and r7 < 1.0:
        return f"🔴 **중단/교체 검토** — 최근 7일 ROAS {r7:.2f} 적자(지출 ₩{s7:,.0f}), 어제도 구매 {py}건."
    if r7 >= 2.5:
        return f"🟢 **증액 여지** — 최근 7일 ROAS {r7:.2f} 우수(지출 ₩{s7:,.0f})."
    if py == 0 and sy >= 20000:
        return f"🟡 **오늘 관찰** — 어제 ₩{sy:,.0f} 쓰고 구매 0건(최근 7일 ROAS {r7:.2f}). 지속 시 소재 점검."
    if r7 < 1.0:
        return f"🟡 **관찰** — 최근 7일 ROAS {r7:.2f} 본전 미만(지출 ₩{s7:,.0f}). 소액이라 유지."
    return f"🟢 **유지** — 최근 7일 ROAS {r7:.2f} 수익 구간(지출 ₩{s7:,.0f})."


# ==================== 추이 탭 ====================
def render_trend():
    st.caption(
        f"그래프 기간: {date_min:%Y-%m-%d} ~ {date_max:%Y-%m-%d} (최근 {GRAPH_DAYS}일)  ·  "
        f"결과=omni_purchase 기준  ·  "
        f"어제({LATEST:%m-%d}) 지출 0인 캠페인·세트·소재는 그래프에서 제외"
    )

    # ===== 개요 (7 / 14 / 28일) =====
    st.subheader("📊 개요 — 기간별 현재 수치")
    st.caption(f"어제({LATEST:%m-%d}) 지출이 있는 캠페인만 집계(어제 지출 0 캠페인 제외). 최신일 기준 최근 7·14·28일 누적.")

    overview = pd.DataFrame({
        "최근 7일": period_metrics(7),
        "최근 14일": period_metrics(14),
        "최근 28일": period_metrics(28),
    })
    overview = overview.reindex(["총 지출", "구매", "구매 전환값", "ROAS", "구매당 비용"])
    st.table(overview)

    st.divider()

    # ===== 즉시 조치 요약 =====
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

    # ===== ① 캠페인별 =====
    st.header("① 캠페인별 — 지출(막대) & ROAS(선)")
    st.caption("구매전환 캠페인마다 개별 그래프. 파란 막대=일별 지출(왼쪽 축), "
               "주황 선=그날 ROAS, 보라 점선=그날 기준 최근 7일 ROAS(오른쪽 축). "
               "보라 숫자=마지막 날의 최근 7일 ROAS. 회색 점선=ROAS 1.0(본전).")

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

    # ===== ② 광고세트 & 그 안의 소재 =====
    st.header("② 광고세트별 성과 + 소재별 성과")
    st.caption("캠페인 아래 광고세트마다: 세트 그래프(지출 막대 + ROAS 선, 보라 숫자=마지막 날 최근 7일 ROAS) → "
               "그 세트의 소재별 지출 선(ROAS≥0.1은 소재 색으로 위에 표기) → 세트 조치사항 순으로 보여줍니다. "
               "모든 그래프의 가로축(날짜)은 동일한 14일 창으로 맞춰 데이터 없는 날은 비워둡니다.")

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
            sub = cdf[cdf["adset"] == aset]
            g = sub.groupby("date").agg(
                spend=("spend", "sum"), purchase_value=("purchase_value", "sum"),
            ).reset_index()
            if g["spend"].sum() <= 0:
                continue
            g["roas"] = (g["purchase_value"] / g["spend"]).where(g["spend"] > 0, 0)
            a_spend = g["spend"].sum(); a_val = g["purchase_value"].sum()
            a_roas = a_val / a_spend if a_spend else 0
            st.markdown(f"**🎯 {aset}**  ·  지출 ₩{a_spend:,.0f} · ROAS {a_roas:.2f}")

            # (1) 광고세트 성과 그래프
            dual_axis_chart(g)

            # (2) 이 세트의 소재별 성과 그래프
            ad_sub = df_ad[(df_ad["campaign"] == camp) & (df_ad["adset"] == aset)]
            if len(ad_sub):
                st.caption("↳ 소재별 지출 · ROAS")
                multiline_spend_with_roas(daily_spend_roas(ad_sub, "ad"), "ad")

            # (3) 세트 조치사항 한 줄
            st.markdown("**조치사항** · " + adset_action_line(sub))
            st.markdown("")
        st.divider()

    st.caption(
        "데이터는 스냅샷(CSV)입니다. 갱신하려면 meta-ads MCP get_insights(level=ad, "
        "time_breakdown=day, 최근 28일)를 다시 뽑아 data/insights_daily.csv를 재생성하세요. "
        "어트리뷰션 기본 창(클릭 7일/조회 1일)."
    )


# ==================== 소재 성과 탭 ====================
def creative_perf(days: int) -> pd.DataFrame:
    """선택 기간 동안 소재(ad)별로 집계. 중단된 소재도 포함(이력 검토용)."""
    start = LATEST - pd.Timedelta(days=days - 1)
    d = df_raw[df_raw["date"] >= start]
    g = d.groupby("ad").agg(
        spend=("spend", "sum"),
        impressions=("impressions", "sum"),
        clicks=("clicks", "sum"),
        purchase=("purchase", "sum"),
        purchase_value=("purchase_value", "sum"),
        campaign=("campaign", "first"),
        adset=("adset", "first"),
    ).reset_index()
    g = g[g["spend"] > 0].copy()
    g["roas"] = (g["purchase_value"] / g["spend"]).where(g["spend"] > 0, 0)
    g["ctr"] = (g["clicks"] / g["impressions"] * 100).where(g["impressions"] > 0, 0)
    return g


def _short(name: str, n: int = 34) -> str:
    return name if len(name) <= n else name[: n - 1] + "…"


SORT_COL = {"지출": "spend", "ROAS": "roas", "CTR": "ctr"}


def render_cards(sec: pd.DataFrame, cmap: pd.DataFrame, key: str, ncol: int = 4):
    if sec.empty:
        st.info("해당하는 소재가 없습니다.")
        return
    sort_by = st.radio("정렬 기준 (내림차순)", list(SORT_COL), horizontal=True, key=key)
    sec = sec.sort_values(SORT_COL[sort_by], ascending=False).reset_index(drop=True)
    recs = list(sec.itertuples())
    for i in range(0, len(recs), ncol):
        cols = st.columns(ncol)
        for col, r in zip(cols, recs[i:i + ncol]):
            with col:
                info = cmap.loc[r.ad] if r.ad in cmap.index else None
                imgrel = info["img"] if info is not None else None
                imgpath = os.path.join(DATA_DIR, imgrel) if imgrel else None
                if imgpath and os.path.exists(imgpath):
                    st.image(imgpath, use_container_width=True)
                else:
                    st.markdown(
                        "<div style='width:100%;aspect-ratio:1;background:#f1f5f9;"
                        "border-radius:8px;display:flex;align-items:center;"
                        "justify-content:center;font-size:2rem;color:#94a3b8'>🖼️</div>",
                        unsafe_allow_html=True,
                    )
                is_video = bool(info["is_video"]) if info is not None else False
                tag = "🎬 영상" if is_video else "🖼️ 이미지"
                roas_color = "#16a34a" if r.roas >= 1 else ("#f59e0b" if r.roas >= 0.5 else "#dc2626")
                ctr_color = "#16a34a" if r.ctr >= 2.5 else "#64748b"
                st.markdown(
                    f"<div style='font-size:0.82rem;line-height:1.45;margin-top:4px'>"
                    f"<div style='font-weight:600' title=\"{r.ad}\">{_short(r.ad)}</div>"
                    f"<div style='color:#64748b;font-size:0.72rem'>{tag}</div>"
                    f"지출 <b>₩{r.spend:,.0f}</b><br>"
                    f"ROAS <b style='color:{roas_color}'>{r.roas:.2f}</b> · "
                    f"CTR <b style='color:{ctr_color}'>{r.ctr:.1f}%</b><br>"
                    f"구매 <b>{int(r.purchase)}</b>건 · 매출 ₩{r.purchase_value:,.0f}"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)


def render_creative_list(perf: pd.DataFrame, days: int):
    """소재를 리스트(표)로 — 제품(밀크/버블) 또는 포맷(영상/이미지)으로 그룹.
    컬럼: 소재명 · 게시일 · 지출 · CTR · 후킹 · 지속시간 · ROAS. 표 머리글 클릭으로 정렬."""
    if cmeta.empty:
        st.info("소재 메타데이터(data/creative_meta.csv)가 없습니다. "
                "scripts/build_creative_meta.py 로 생성하세요.")
        return

    m = perf.merge(
        cmeta[["ad", "created_date", "product_line", "format", "hook_rate", "avg_watch_sec"]],
        on="ad", how="left",
    )
    m["product_line"] = m["product_line"].fillna("기타")
    m["format"] = m["format"].fillna("이미지")

    gsel = st.radio(
        "그룹 기준", ["밀크 / 버블 (제품)", "영상 / 이미지 (포맷)"],
        horizontal=True, key="list_group",
    )
    if gsel.startswith("밀크"):
        gcol, order = "product_line", ["밀크", "버블", "기타"]
    else:
        gcol, order = "format", ["영상", "이미지"]

    sort_label = st.radio(
        "정렬 기준 (내림차순)", ["지출", "ROAS", "CTR", "후킹", "지속시간", "최신순"],
        horizontal=True, key="list_sort",
    )
    SORTMAP = {"지출": "spend", "ROAS": "roas", "CTR": "ctr",
               "후킹": "hook_rate", "지속시간": "avg_watch_sec", "최신순": "created_date"}

    st.caption(
        f"지출·CTR·ROAS는 선택 기간(최근 {days}일) 기준 · 게시일·후킹·지속시간은 소재 고유값(최근 90일). "
        "후킹 = 3초 동영상 재생 ÷ 노출 × 100, 지속시간 = 평균 동영상 재생 시간(초) — 영상만(이미지는 —). "
        "정렬은 위 '정렬 기준'을 바꿔서 하세요."
    )

    def fmt_num(x, suffix="", nan="—"):
        return nan if pd.isna(x) else f"{x:.1f}{suffix}"

    for gv in order:
        sub = m[m[gcol] == gv].copy()
        if sub.empty:
            continue
        gs = sub["spend"].sum(); gval = sub["purchase_value"].sum()
        gr = gval / gs if gs else 0
        st.markdown(f"**{gv}** · 소재 {len(sub)}개 · 지출 ₩{gs:,.0f} · "
                    f"매출 ₩{gval:,.0f} · ROAS {gr:.2f}")
        sub = sub.sort_values(SORTMAP[sort_label], ascending=False, na_position="last")
        disp = pd.DataFrame({
            "소재명": sub["ad"].values,
            "게시일": sub["created_date"].fillna("—").values,
            "지출(원)": [f"₩{x:,.0f}" for x in sub["spend"]],
            "CTR(%)": [f"{x:.2f}" for x in sub["ctr"]],
            "후킹(%)": [fmt_num(x) for x in sub["hook_rate"]],
            "지속시간(초)": [fmt_num(x) for x in sub["avg_watch_sec"]],
            "ROAS": [f"{x:.2f}" for x in sub["roas"]],
        })
        st.dataframe(
            disp, hide_index=True, use_container_width=True,
            column_config={
                "소재명": st.column_config.Column(width="large"),
                "게시일": st.column_config.Column(width="small"),
                "후킹(%)": st.column_config.Column(help="3초 동영상 재생 ÷ 노출 (영상만)"),
                "지속시간(초)": st.column_config.Column(help="평균 동영상 재생 시간 (영상만)"),
            },
        )


def render_creative():
    st.caption(
        "소재(광고)를 썸네일로 보고 성과를 바로 확인합니다. 선택 기간 동안 지출이 있었던 소재를 "
        "모두 보여줍니다(중단된 소재 포함, 이력 검토용). 영상 소재는 대표 이미지(🎬)로 표시됩니다. "
        f"ROAS·CTR·구매는 구매 전환값(omni_purchase) 기준. CTR = 전체 클릭 ÷ 노출 × 100."
    )

    c1, c2 = st.columns([1, 2])
    with c1:
        days = st.radio("집계 기간", [7, 14, 28], index=1, horizontal=True,
                        format_func=lambda d: f"최근 {d}일", key="cre_days")
    start = LATEST - pd.Timedelta(days=days - 1)
    with c2:
        st.caption(f"기간: {start:%Y-%m-%d} ~ {LATEST:%Y-%m-%d}")

    perf = creative_perf(days)
    if perf.empty:
        st.info("선택 기간에 지출이 있는 소재가 없습니다.")
        return

    cmap = creatives.set_index("ad") if len(creatives) else pd.DataFrame().reindex(columns=["img", "is_video"])

    high_roas = perf[perf["roas"] >= 0.5]
    high_ctr = perf[perf["ctr"] >= 2.5]
    low = perf[(perf["roas"] < 0.5) & (perf["ctr"] < 2.5)]

    tot_spend = perf["spend"].sum(); tot_val = perf["purchase_value"].sum()
    tot_roas = tot_val / tot_spend if tot_spend else 0
    st.markdown(
        f"**소재 {len(perf)}개** · 지출 ₩{tot_spend:,.0f} · 매출 ₩{tot_val:,.0f} · "
        f"ROAS {tot_roas:.2f}  |  고성과(ROAS≥0.5) {len(high_roas)} · "
        f"고CTR(≥2.5%) {len(high_ctr)} · 저성과 {len(low)}"
    )
    st.divider()

    st.subheader(f"🟢 고성과 · ROAS ≥ 0.5  ({len(high_roas)}개)")
    st.caption("구매 전환이 어느 정도 발생한 소재. 증액·확장 후보.")
    render_cards(high_roas, cmap, key="sort_hr")
    st.divider()

    st.subheader(f"🔵 고CTR · CTR ≥ 2.5%  ({len(high_ctr)}개)")
    st.caption("클릭률이 높아 후킹·소구가 잘 먹히는 소재. 전환이 약하면 랜딩/오퍼 점검.")
    render_cards(high_ctr, cmap, key="sort_hc")
    st.divider()

    st.subheader(f"🔴 저성과 · ROAS < 0.5 이고 CTR < 2.5%  ({len(low)}개)")
    st.caption("구매·클릭 모두 약한 소재. OFF·교체 검토 대상.")
    render_cards(low, cmap, key="sort_low")

    st.divider()
    st.subheader("📋 소재 리스트 — 제품 · 포맷별")
    st.caption("썸네일 없이 표로 봅니다. 밀크/버블(제품) 또는 영상/이미지(포맷)로 그룹을 바꿔가며 "
               "게시일·지출·CTR·후킹·지속시간·ROAS를 비교하세요.")
    render_creative_list(perf, days)


# ==================== 레이아웃 ====================
st.title("🏢 광고 성과 대시보드")

tab_trend, tab_creative = st.tabs(["📈 추이", "🖼️ 소재 성과"])
with tab_trend:
    render_trend()
with tab_creative:
    render_creative()
