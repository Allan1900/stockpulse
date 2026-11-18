"""
📊 数据浏览器 — 对标 Wind EDB 数据浏览器

功能:
- 截面查询：选日期+指标，查看全市场横截面数据
- 时序查询：选股票+指标+时间，查看指标走势
- 全市场均值：查看某指标全市场每日均值/中位数
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta

st.set_page_config(page_title="数据浏览器", layout="wide")
st.title("📊 数据浏览器")
st.caption("对标 Wind EDB 数据浏览器 · 截面 / 时序 / 全市场均值")

from engine.data_browser import (
    cross_section, time_series, market_average,
    get_available_dates, get_indicator_list, INDICATOR_GROUPS,
)
from engine.api_adapter import get_stock_list, get_industries

# Sidebar helpers
stocks_df = get_stock_list()
industries = sorted(stocks_df["industry"].dropna().unique())
indicators = get_indicator_list()
ind_by_group = {}
for code, label, group in indicators:
    ind_by_group.setdefault(group, []).append((code, label))

ind_dict = dict((c, l) for c, l, _ in indicators)

# Mode selector
mode = st.radio(
    "查看模式",
    ["📋 截面 (横截面)", "📈 时序 (时间序列)", "📊 全市场均值"],
    horizontal=True,
)

# ════════════════════════════════════════
# CROSS-SECTION MODE
# ════════════════════════════════════════
if mode == "📋 截面 (横截面)":
    col_p1, col_p2, col_p3 = st.columns([2, 2, 1])

    with col_p1:
        dates = get_available_dates("daily_basic")
        if not dates:
            st.error("无可用日期数据"); st.stop()
        sel_date = st.selectbox("选择交易日", dates, index=0)

    with col_p2:
        sel_inds = []
        with st.expander("选择指标", expanded=True):
            for group, items in ind_by_group.items():
                codes = [c for c, _ in items]
                default = [codes[0]] if codes else []
                opts = st.multiselect(
                    group, options=codes,
                    format_func=lambda c: ind_dict.get(c, c),
                    default=default,
                    key=f"xs_{group}",
                )
                sel_inds.extend(opts)

    with col_p3:
        sel_industry = st.multiselect("行业过滤", industries, default=[])
        top_n = st.number_input("显示条数", 10, 5000, 100, step=10)

    if not sel_inds:
        st.warning("请至少选择一个指标"); st.stop()

    with st.spinner(f"加载 {sel_date} 截面数据..."):
        df = cross_section(
            sel_date, sel_inds,
            industry=sel_industry if sel_industry else None,
            top_n=top_n,
        )

    if df.empty:
        st.warning(f"{sel_date} 无数据"); st.stop()

    st.success(f"✅ {len(df)} 只股票 · {len(sel_inds)} 个指标")

    # Display columns
    display_cols = ["ts_code", "name", "industry"] + sel_inds
    display_cols = [c for c in display_cols if c in df.columns]
    df_display = df[display_cols].copy()
    df_display.columns = ["代码", "名称", "行业"] + [ind_dict.get(c, c) for c in sel_inds]
    st.dataframe(df_display, use_container_width=True, hide_index=True)

    # Distribution viz
    if len(sel_inds) >= 1:
        st.subheader("📊 分布可视化")
        col_v1, col_v2 = st.columns(2)

        with col_v1:
            col_name = sel_inds[0]
            label = ind_dict.get(col_name, col_name)
            fig = px.histogram(
                df, x=col_name, nbins=50,
                title=f"{label} 分布 ({sel_date})",
                labels={col_name: label},
                color_discrete_sequence=["#00d4aa"],
            )
            fig.update_layout(height=400, template="plotly_dark", showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

        with col_v2:
            if "industry" in df.columns:
                fig2 = px.box(
                    df, x="industry", y=col_name,
                    title=f"{label} 行业分布",
                    labels={"industry": "行业", col_name: label},
                    color="industry",
                    color_discrete_sequence=px.colors.qualitative.Set2,
                )
                fig2.update_layout(
                    height=400, template="plotly_dark",
                    xaxis_tickangle=-45, showlegend=False,
                )
                st.plotly_chart(fig2, use_container_width=True)

        if len(sel_inds) >= 2:
            fig3 = px.scatter(
                df, x=sel_inds[0], y=sel_inds[1],
                color="industry" if "industry" in df.columns else None,
                hover_data=["ts_code", "name"],
                title=f"{ind_dict.get(sel_inds[0], sel_inds[0])} vs "
                      f"{ind_dict.get(sel_inds[1], sel_inds[1])}",
                opacity=0.6,
            )
            fig3.update_layout(height=500, template="plotly_dark")
            st.plotly_chart(fig3, use_container_width=True)

    # Export
    csv = df[display_cols].to_csv(index=False).encode("utf-8")
    st.download_button(
        "📥 导出 CSV", data=csv,
        file_name=f"cross_section_{sel_date}.csv",
        mime="text/csv", use_container_width=True,
    )

# ════════════════════════════════════════
# TIME SERIES MODE
# ════════════════════════════════════════
elif mode == "📈 时序 (时间序列)":
    col_t1, col_t2, col_t3 = st.columns([2, 2, 1])

    with col_t1:
        stock_labels = {
            f"{r['ts_code']} — {r['name']}": r['ts_code']
            for _, r in stocks_df.iterrows()
        }
        sel_labels = st.multiselect(
            "选择股票 (最多5只)", options=list(stock_labels.keys()),
            max_selections=5,
        )
        sel_stocks = [stock_labels[l] for l in sel_labels]

    with col_t2:
        sel_ts_inds = []
        with st.expander("选择指标 (最多3个)", expanded=True):
            for group, items in ind_by_group.items():
                opts = st.multiselect(
                    group, options=[c for c, _ in items],
                    format_func=lambda c: ind_dict.get(c, c),
                    key=f"ts_{group}",
                )
                sel_ts_inds.extend(opts)
                if len(sel_ts_inds) > 3:
                    sel_ts_inds = sel_ts_inds[:3]
                    st.caption("⚠️ 最多3个指标")
                    break

    with col_t3:
        ts_start = st.text_input(
            "起始",
            (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d"),
        )
        ts_end = st.text_input(
            "结束", datetime.now().strftime("%Y-%m-%d"),
        )

    if not sel_stocks or not sel_ts_inds:
        st.info("👆 请选择股票和指标后查看数据"); st.stop()

    with st.spinner("加载时序数据..."):
        df = time_series(
            sel_stocks, sel_ts_inds,
            ts_start.replace("-", ""),
            ts_end.replace("-", ""),
        )

    if df.empty:
        st.warning("无匹配数据"); st.stop()

    st.success(f"✅ {len(df)} 个交易日")

    # Chart
    st.subheader("📈 走势图")

    if len(sel_ts_inds) == 1:
        fig = go.Figure()
        for stock in sel_stocks:
            col_name = f"{stock}_{sel_ts_inds[0]}"
            if col_name in df.columns:
                fig.add_trace(go.Scatter(
                    x=df["trade_date"], y=df[col_name],
                    mode="lines+markers", name=stock,
                    connectgaps=False,
                ))
        fig.update_layout(
            title=f"{ind_dict.get(sel_ts_inds[0], sel_ts_inds[0])} 走势对比",
            yaxis_title=ind_dict.get(sel_ts_inds[0], sel_ts_inds[0]),
            height=450, template="plotly_dark", hovermode="x unified",
        )
    else:
        fig = make_subplots(
            rows=len(sel_ts_inds), cols=1,
            shared_xaxes=True,
            subplot_titles=[ind_dict.get(i, i) for i in sel_ts_inds],
            vertical_spacing=0.08,
        )
        for row_idx, ind in enumerate(sel_ts_inds, 1):
            for stock in sel_stocks:
                col_name = f"{stock}_{ind}"
                if col_name in df.columns:
                    fig.add_trace(
                        go.Scatter(x=df["trade_date"], y=df[col_name],
                                   mode="lines", name=f"{stock}"),
                        row=row_idx, col=1,
                    )
        fig.update_layout(
            height=350 * len(sel_ts_inds),
            template="plotly_dark", hovermode="x unified",
        )

    st.plotly_chart(fig, use_container_width=True)

    st.subheader("📄 数据表")
    st.dataframe(df, use_container_width=True, hide_index=True)

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "📥 导出 CSV", data=csv,
        file_name=f"timeseries_{'_'.join(sel_stocks)}.csv",
        mime="text/csv", use_container_width=True,
    )

# ════════════════════════════════════════
# MARKET AVERAGE MODE
# ════════════════════════════════════════
elif mode == "📊 全市场均值":
    col_m1, col_m2, col_m3 = st.columns([2, 1, 1])

    flat_inds = [(c, l) for c, l, _ in indicators]

    with col_m1:
        sel_ind_code = st.selectbox(
            "选择指标", options=[c for c, _ in flat_inds],
            format_func=lambda c: dict(flat_inds).get(c, c),
            index=9,
        )
        sel_ind_label = dict(flat_inds).get(sel_ind_code, sel_ind_code)

    with col_m2:
        ma_start = st.text_input(
            "起始",
            (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"),
        )
    with col_m3:
        ma_end = st.text_input(
            "结束", datetime.now().strftime("%Y-%m-%d"),
        )

    with st.spinner(f"计算 {sel_ind_label} 全市场均值..."):
        df = market_average(
            sel_ind_code,
            ma_start.replace("-", ""),
            ma_end.replace("-", ""),
        )

    if df.empty:
        st.warning("无数据"); st.stop()

    st.success(f"✅ {len(df)} 个交易日 · 日均 {int(df['count'].mean())} 只股票")

    # Main chart: mean ± std band
    st.subheader("📊 均值走势")
    fig = go.Figure()

    # Std band
    fig.add_trace(go.Scatter(
        x=pd.concat([df["trade_date"], df["trade_date"][::-1]]),
        y=pd.concat([df["mean"] + df["std"], (df["mean"] - df["std"])[::-1]]),
        fill="toself",
        fillcolor="rgba(0, 212, 170, 0.2)",
        line=dict(color="rgba(0,212,170,0)"),
        name="±1σ",
    ))
    # Mean line
    fig.add_trace(go.Scatter(
        x=df["trade_date"], y=df["mean"],
        mode="lines+markers", name="均值",
        line=dict(color="#00d4aa", width=2),
    ))
    # Median line
    fig.add_trace(go.Scatter(
        x=df["trade_date"], y=df["median"],
        mode="lines", name="中位数",
        line=dict(color="#ffd93d", width=1.5, dash="dash"),
    ))

    fig.update_layout(
        title=f"全市场 {sel_ind_label} 均值/中位数",
        yaxis_title=sel_ind_label,
        height=450, template="plotly_dark",
        hovermode="x unified",
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Stats table
    st.subheader("📄 每日统计")
    display = df.copy()
    display["mean"] = display["mean"].round(2)
    display["median"] = display["median"].round(2)
    display["std"] = display["std"].round(2)
    display.columns = ["交易日", "均值", "中位数", "标准差", "股票数", "Q25", "Q75"]
    st.dataframe(display, use_container_width=True, hide_index=True)

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "📥 导出 CSV", data=csv,
        file_name=f"market_avg_{sel_ind_code}.csv",
        mime="text/csv", use_container_width=True,
    )