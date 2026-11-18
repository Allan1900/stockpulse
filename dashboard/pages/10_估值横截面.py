"""
📐 估值横截面 — 对标 Bloomberg RV (Relative Value)

功能:
- 全市场估值快照 (PE/PB/PS 排行)
- 行业估值水位 (历史分位数)
- 估值 vs 涨幅散点图
- 行业估值对比
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta

st.set_page_config(page_title="估值横截面", layout="wide")
st.title("📐 估值横截面")
st.caption("对标 Bloomberg RV · 全市场估值分布 / 行业估值水位 / 估值 vs 涨幅")

from engine.valuation import get_valuation_snapshot, industry_valuation_percentile, get_available_valuation_dates
from engine.api_adapter import get_industries

industries = sorted(get_industries())
dates = get_available_valuation_dates()

if not dates:
    st.error("daily_basic 数据不可用"); st.stop()

# ── 控制栏 ──────────────────────────────────────────
col_c1, col_c2, col_c3 = st.columns([2, 2, 1])

with col_c1:
    sel_date = st.selectbox("选择交易日", dates, index=0,
                            key="val_date")

with col_c2:
    val_metric = st.selectbox(
        "估值指标", ["pe_ttm", "pe", "pb", "ps", "ps_ttm", "dv_ratio"],
        format_func=lambda x: {
            "pe_ttm": "PE-TTM", "pe": "PE", "pb": "PB",
            "ps": "PS", "ps_ttm": "PS-TTM", "dv_ratio": "股息率%",
        }.get(x, x),
        index=0, key="val_metric",
    )

with col_c3:
    top_n = st.number_input("TOP N", 10, 5000, 50, step=10,
                            key="val_topn")

# ── 加载数据 ─────────────────────────────────────────
with st.spinner(f"加载 {sel_date} 估值数据..."):
    df = get_valuation_snapshot(sel_date)

if df.empty:
    st.warning(f"{sel_date} 无数据"); st.stop()

st.success(f"✅ {len(df)} 只股票 · {df['industry'].nunique()} 个行业")

# ═══════════════════════════════════════════════════════
# Tab 1: 估值排行
# ═══════════════════════════════════════════════════════
tab_rank, tab_industry, tab_scatter, tab_watermark = st.tabs(
    ["🏆 估值排行", "🏭 行业估值水位", "🎯 估值 vs 涨幅", "📊 估值水位图"]
)

with tab_rank:
    # 过滤异常值
    metric_label = {
        "pe_ttm": "PE-TTM", "pe": "PE", "pb": "PB",
        "ps": "PS", "ps_ttm": "PS-TTM", "dv_ratio": "股息率%",
    }.get(val_metric, val_metric)

    if val_metric in ["pe_ttm", "pe", "pb", "ps", "ps_ttm"]:
        valid = df[(df[val_metric] > 0) & (df[val_metric] < 500)]
    else:
        valid = df[df[val_metric] > 0]

    st.subheader(f"🔺 {metric_label} 最高 TOP{top_n}")
    top = valid.nlargest(top_n, val_metric)
    display = top[["ts_code", "name", "industry", val_metric, "total_mv"]].copy()
    display.columns = ["代码", "名称", "行业", metric_label, "总市值(亿)"]
    display[metric_label] = display[metric_label].round(2)
    display["总市值(亿)"] = (display["总市值(亿)"] / 1e8).round(2)
    st.dataframe(display, use_container_width=True, hide_index=True)

    st.subheader(f"🔻 {metric_label} 最低 TOP{top_n}")
    bottom = valid.nsmallest(top_n, val_metric)
    display2 = bottom[["ts_code", "name", "industry", val_metric, "total_mv"]].copy()
    display2.columns = ["代码", "名称", "行业", metric_label, "总市值(亿)"]
    display2[metric_label] = display2[metric_label].round(2)
    display2["总市值(亿)"] = (display2["总市值(亿)"] / 1e8).round(2)
    st.dataframe(display2, use_container_width=True, hide_index=True)

    # 分布直方图
    fig = px.histogram(
        valid, x=val_metric, nbins=60,
        title=f"全市场 {metric_label} 分布 ({sel_date})",
        labels={val_metric: metric_label},
        color_discrete_sequence=["#00d4aa"],
    )
    fig.update_layout(height=400, template="plotly_dark", showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

# ═══════════════════════════════════════════════════════
# Tab 2: 行业估值水位
# ═══════════════════════════════════════════════════════
with tab_industry:
    with st.spinner("计算行业估值分位数（历史5年）..."):
        ind_df = industry_valuation_percentile(sel_date)

    if ind_df.empty:
        st.warning("行业估值分位数计算失败"); st.stop()

    st.subheader("🏭 行业 PE 估值水位 (历史分位数)")
    st.caption("分位数越高 → 当前估值越贵 (接近100%=历史最高, 接近0%=历史最低)")

    # PE 水位图
    fig_pe = px.bar(
        ind_df.sort_values("pe_percentile", ascending=True),
        y="industry", x="pe_percentile",
        color="pe_percentile",
        color_continuous_scale=["#00d4aa", "#ffd93d", "#ff6b6b"],
        range_color=[0, 100],
        title="PE-TTM 历史分位数 (低→高)",
        labels={"industry": "行业", "pe_percentile": "PE分位数%",
                "pe_current": "当前PE"},
        hover_data=["pe_current"],
        text="pe_percentile",
    )
    fig_pe.update_layout(height=800, template="plotly_dark",
                          yaxis=dict(autorange="reversed"))
    fig_pe.update_traces(texttemplate="%{text:.0f}", textposition="outside")
    st.plotly_chart(fig_pe, use_container_width=True)

    # 数据表
    st.subheader("📄 行业估值明细")
    display_ind = ind_df[["industry", "pe_current", "pe_percentile",
                           "pb_current", "pb_percentile"]].copy()
    display_ind.columns = ["行业", "当前PE", "PE分位数%",
                            "当前PB", "PB分位数%"]
    display_ind["PE分位数%"] = display_ind["PE分位数%"].round(1)
    display_ind["PB分位数%"] = display_ind["PB分位数%"].round(1)
    display_ind["当前PE"] = display_ind["当前PE"].round(2)
    display_ind["当前PB"] = display_ind["当前PB"].round(2)
    st.dataframe(display_ind, use_container_width=True, hide_index=True)

# ═══════════════════════════════════════════════════════
# Tab 3: 估值 vs 涨幅
# ═══════════════════════════════════════════════════════
with tab_scatter:
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        x_metric = st.selectbox(
            "X 轴", ["pe_ttm", "pe", "pb", "ps", "total_mv", "dv_ratio"],
            index=0,
            format_func=lambda x: {
                "pe_ttm": "PE-TTM", "pe": "PE", "pb": "PB",
                "ps": "PS", "total_mv": "总市值", "dv_ratio": "股息率%",
            }.get(x, x),
            key="scatter_x",
        )
    with col_s2:
        y_metric = st.selectbox(
            "Y 轴", ["pct_chg", "pe_ttm", "pe", "pb", "total_mv", "dv_ratio"],
            index=0,
            format_func=lambda x: {
                "pct_chg": "当日涨幅%", "pe_ttm": "PE-TTM", "pe": "PE",
                "pb": "PB", "total_mv": "总市值", "dv_ratio": "股息率%",
            }.get(x, x),
            key="scatter_y",
        )

    sel_industry_filter = st.multiselect(
        "行业过滤 (可选)", industries, default=[],
        key="scatter_ind",
    )

    plot_df = df.copy()
    if sel_industry_filter:
        plot_df = plot_df[plot_df["industry"].isin(sel_industry_filter)]

    # 过滤异常值 — 对 PE/PB 类
    if x_metric in ["pe_ttm", "pe", "pb", "ps"]:
        plot_df = plot_df[(plot_df[x_metric] > 0) & (plot_df[x_metric] < 200)]
    if y_metric in ["pe_ttm", "pe", "pb", "ps"]:
        plot_df = plot_df[(plot_df[y_metric] > 0) & (plot_df[y_metric] < 200)]
    if y_metric == "pct_chg":
        plot_df = plot_df[(plot_df[y_metric] > -11) & (plot_df[y_metric] < 11)]

    x_label = {
        "pe_ttm": "PE-TTM", "pe": "PE", "pb": "PB",
        "ps": "PS", "total_mv": "总市值(亿)", "dv_ratio": "股息率%",
    }.get(x_metric, x_metric)
    y_label = {
        "pct_chg": "当日涨幅%", "pe_ttm": "PE-TTM", "pe": "PE",
        "pb": "PB", "total_mv": "总市值(亿)", "dv_ratio": "股息率%",
    }.get(y_metric, y_metric)

    if "total_mv" in [x_metric, y_metric]:
        plot_df = plot_df.copy()
        plot_df["total_mv_b"] = plot_df["total_mv"] / 1e8
        if x_metric == "total_mv":
            x_metric_plot = "total_mv_b"
        if y_metric == "total_mv":
            y_metric_plot = "total_mv_b"

    fig_scatter = px.scatter(
        plot_df,
        x=x_metric_plot if "total_mv_b" in locals() else x_metric,
        y=y_metric_plot if "total_mv_b" in locals() else y_metric,
        color="industry" if not sel_industry_filter else None,
        hover_data=["ts_code", "name", "industry"],
        title=f"{x_label} vs {y_label} ({sel_date})",
        labels={
            x_metric_plot if "total_mv_b" in locals() else x_metric: x_label,
            y_metric_plot if "total_mv_b" in locals() else y_metric: y_label,
        },
        opacity=0.5,
        size_max=10,
    )
    fig_scatter.update_layout(
        height=600, template="plotly_dark",
        hovermode="closest",
    )
    st.plotly_chart(fig_scatter, use_container_width=True)

# ═══════════════════════════════════════════════════════
# Tab 4: 估值水位热力图
# ═══════════════════════════════════════════════════════
with tab_watermark:
    with st.spinner("生成行业估值水位热力图..."):
        ind_df2 = industry_valuation_percentile(sel_date)

    if ind_df2.empty:
        st.stop()

    # PE + PB 双指标水位
    fig_heat = px.scatter(
        ind_df2,
        x="pe_percentile", y="pb_percentile",
        text="industry",
        size=[30] * len(ind_df2),
        color="pe_percentile",
        color_continuous_scale=["#00d4aa", "#ffd93d", "#ff6b6b"],
        range_color=[0, 100],
        title=f"行业估值水位矩阵 — PE vs PB 历史分位数 ({sel_date})",
        labels={
            "pe_percentile": "PE分位数% (低→高)",
            "pb_percentile": "PB分位数% (低→高)",
        },
    )
    fig_heat.update_traces(
        textposition="middle center",
        textfont=dict(size=9),
    )
    fig_heat.update_layout(
        height=700, template="plotly_dark",
        xaxis=dict(range=[-5, 105]),
        yaxis=dict(range=[-5, 105]),
    )
    # 添加象限分割线
    fig_heat.add_hline(y=50, line_dash="dash", line_color="#555", opacity=0.5)
    fig_heat.add_vline(x=50, line_dash="dash", line_color="#555", opacity=0.5)
    # 象限标注
    fig_heat.add_annotation(x=75, y=75, text="⚡高估区", showarrow=False,
                            font=dict(color="#ff6b6b", size=12))
    fig_heat.add_annotation(x=25, y=75, text="🔶PB高/PE低", showarrow=False,
                            font=dict(color="#ffd93d", size=12))
    fig_heat.add_annotation(x=75, y=25, text="🔶PE高/PB低", showarrow=False,
                            font=dict(color="#ffd93d", size=12))
    fig_heat.add_annotation(x=25, y=25, text="🟢低估区", showarrow=False,
                            font=dict(color="#00d4aa", size=12))

    st.plotly_chart(fig_heat, use_container_width=True)

    st.info("💡 **解读**: 左下象限=双低估(机会区) · 右上象限=双高估(风险区) · "
            "左右偏离=估值结构分化")