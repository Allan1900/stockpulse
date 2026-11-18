"""
📊 组合管理 — 对标 Bloomberg PORT / FactSet Portfolio Analytics

功能:
- 创建/管理多个投资组合
- 组合净值追踪 vs 沪深300
- 绩效统计指标 (夏普/回撤/胜率)
- Brinson 归因分析
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta

st.set_page_config(page_title="组合管理", layout="wide")
st.title("📊 组合管理")

from engine.portfolio import (
    list_portfolios, create_portfolio, delete_portfolio,
    get_portfolio, add_holding, remove_holding,
    calc_portfolio_nav, calc_portfolio_stats, brinson_attribution,
)
from engine.api_adapter import get_stock_list, get_stock_names

# ── 侧边栏：组合管理 ──────────────────────────────
stocks_df = get_stock_list()
name_map = dict(zip(stocks_df["ts_code"], stocks_df["name"]))
labels = {f"{r['ts_code']} — {r['name']}": r['ts_code'] for _, r in stocks_df.iterrows()}

with st.sidebar:
    st.subheader("📂 我的组合")
    portfolios = list_portfolios()

    if portfolios.empty:
        st.info("暂无组合，创建一个开始吧")
    else:
        for _, row in portfolios.iterrows():
            col1, col2 = st.columns([3, 1])
            with col1:
                if st.button(f"📁 {row['name']}", key=f"sel_{row['id']}",
                              use_container_width=True, type="secondary"):
                    st.session_state["active_portfolio"] = row["id"]
            with col2:
                if st.button("✕", key=f"del_{row['id']}",
                              help="删除组合"):
                    delete_portfolio(row["id"])
                    st.rerun()

    st.divider()
    with st.form("new_portfolio", clear_on_submit=True):
        new_name = st.text_input("新组合名称", placeholder="如: 低估蓝筹组合")
        new_desc = st.text_input("描述(可选)", placeholder="选股思路")
        if st.form_submit_button("➕ 创建组合", type="primary", use_container_width=True):
            if new_name:
                pid = create_portfolio(new_name, new_desc)
                st.session_state["active_portfolio"] = pid
                st.rerun()

# ── 查不到活跃组合时提示 ─────────────────────────
if "active_portfolio" not in st.session_state:
    st.info("👈 在左侧创建或选择一个组合开始分析")
    st.stop()

pid = st.session_state["active_portfolio"]
info, holdings = get_portfolio(pid)

if info is None:
    st.warning("组合已删除，请重新选择")
    del st.session_state["active_portfolio"]
    st.stop()

# ── 组合信息展示 ──────────────────────────────────
total_weight = holdings["weight_pct"].sum() if not holdings.empty else 0
col_h1, col_h2, col_h3, col_h4 = st.columns([2, 1, 1, 1])
with col_h1:
    st.markdown(f"### {info['name']}")
    if info["description"]:
        st.caption(info["description"])
with col_h2:
    st.metric("持仓股票", len(holdings) if not holdings.empty else 0)
with col_h3:
    st.metric("总权重", f"{total_weight:.1f}%" if not holdings.empty else "0%")
with col_h4:
    created = info["created_at"][:10] if info.get("created_at") else "—"
    st.metric("创建日期", created)

# ── Tab 布局 ──────────────────────────────────────
tab_holdings, tab_nav, tab_stats, tab_attribution = st.tabs(
    ["📋 持仓管理", "📈 净值走势", "📊 绩效统计", "🔬 Brinson 归因"]
)

# ═══════════════════════════════════════════════════════
# TAB 1: 持仓管理
# ═══════════════════════════════════════════════════════
with tab_holdings:
    col_a, col_b = st.columns([2, 1])

    with col_a:
        st.markdown("**当前持仓**")
        if holdings.empty:
            st.info("组合为空，在右侧添加股票")
        else:
            # 合并显示名称
            display = holdings.copy()
            display["股票名称"] = display.apply(
                lambda r: f"{r['ts_code']} — {r.get('name', '')}", axis=1)
            display["权重%"] = display["weight_pct"].round(1)
            display["行业"] = display.get("industry", "")
            show = display[["股票名称", "权重%", "行业"]]
            show.index = range(1, len(show) + 1)

            # 权重饼图
            fig_pie = px.pie(
                display, values="weight_pct", names="股票名称",
                title="持仓权重分布",
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig_pie.update_layout(margin=dict(t=30, b=10, l=10, r=10),
                                  height=350)

            col_p1, col_p2 = st.columns([1.5, 1])
            with col_p1:
                st.dataframe(show, use_container_width=True, hide_index=False)
            with col_p2:
                st.plotly_chart(fig_pie, use_container_width=True)

            # 删除持仓
            st.markdown("---")
            del_code = st.selectbox(
                "选择要移除的股票", options=display["股票名称"].tolist(),
                key="del_holding")
            if st.button("🗑 移除选中股票", type="secondary"):
                code = display[display["股票名称"] == del_code]["ts_code"].iloc[0]
                remove_holding(pid, code)
                st.rerun()

    with col_b:
        st.markdown("**添加股票到组合**")
        with st.form("add_holding"):
            sel_label = st.selectbox(
                "选择股票", options=list(labels.keys()),
                placeholder="搜索股票代码或名称", label_visibility="collapsed")
            weight = st.number_input("权重%", 1.0, 100.0, 10.0, 1.0,
                                     key="new_weight")
            submitted = st.form_submit_button("➕ 加入组合",
                                               type="primary",
                                               use_container_width=True)
            if submitted:
                code = labels[sel_label]
                # 检查是否已存在
                if not holdings.empty and code in holdings["ts_code"].values:
                    st.warning("该股票已在组合中")
                else:
                    result = add_holding(pid, code, weight)
                    if result is True:
                        st.success(f"已加入: {sel_label}")
                        st.rerun()
                    else:
                        st.error(f"添加失败: {result}")

# ═══════════════════════════════════════════════════════
# TAB 2: 净值走势
# ═══════════════════════════════════════════════════════
with tab_nav:
    if holdings.empty:
        st.info("组合为空，无法计算净值")
        st.stop()

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        nav_start = st.text_input("起始日期", (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"))
    with col_d2:
        nav_end = st.text_input("结束日期", datetime.now().strftime("%Y-%m-%d"))

    if st.button("📈 计算净值", type="primary"):
        with st.spinner("计算组合净值..."):
            nav_df = calc_portfolio_nav(
                pid,
                start_date=nav_start.replace("-", ""),
                end_date=nav_end.replace("-", ""),
            )

        if nav_df.empty:
            st.warning("净值计算失败，请检查持仓和日期范围")
            st.stop()

        # 净值走势图
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=nav_df["trade_date"], y=nav_df["nav"],
            mode="lines", name="组合净值",
            line=dict(color="#00d4aa", width=2),
        ))
        if "bench_nav" in nav_df.columns and nav_df["bench_nav"].notna().any():
            fig.add_trace(go.Scatter(
                x=nav_df["trade_date"], y=nav_df["bench_nav"],
                mode="lines", name="沪深300",
                line=dict(color="#ff6b6b", width=1.5, dash="dash"),
            ))

        fig.update_layout(
            title="组合净值 vs 沪深300",
            xaxis_title="日期",
            yaxis_title="净值 (基日=1.0)",
            hovermode="x unified",
            height=500,
            legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
            template="plotly_dark",
        )
        st.plotly_chart(fig, use_container_width=True)

        # 超额收益图
        if "excess_return" in nav_df.columns:
            fig_ex = go.Figure()
            fig_ex.add_trace(go.Bar(
                x=nav_df["trade_date"],
                y=nav_df["excess_return"] * 100,
                name="日超额收益%",
                marker_color=nav_df["excess_return"].apply(
                    lambda x: "#00d4aa" if x >= 0 else "#ff6b6b"),
            ))
            fig_ex.update_layout(
                title="每日超额收益 (组合 — 沪深300)",
                xaxis_title="日期",
                yaxis_title="超额收益%",
                height=300,
                template="plotly_dark",
                showlegend=False,
            )
            st.plotly_chart(fig_ex, use_container_width=True)

# ═══════════════════════════════════════════════════════
# TAB 3: 绩效统计
# ═══════════════════════════════════════════════════════
with tab_stats:
    st.markdown("**绩效统计指标**")
    stats_start = st.text_input("统计区间起始", (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"),
                                 key="stats_start")
    stats_end = st.text_input("统计区间结束", datetime.now().strftime("%Y-%m-%d"),
                               key="stats_end")

    if st.button("📊 计算绩效", type="primary", key="calc_stats"):
        nav_df = calc_portfolio_nav(
            pid,
            start_date=stats_start.replace("-", ""),
            end_date=stats_end.replace("-", ""),
        )
        if nav_df.empty:
            st.warning("数据不足")
            st.stop()

        stats = calc_portfolio_stats(nav_df)
        if not stats:
            st.warning("无法计算统计指标")
            st.stop()

        # 指标卡片展示
        metric_cols = st.columns(4)
        metric_pairs = [
            ("总收益率", "年化收益率"),
            ("夏普比率", "最大回撤"),
            ("胜率(日)", "年化波动率"),
            ("超额收益", "信息比率"),
        ]
        for i, (k1, k2) in enumerate(metric_pairs):
            with metric_cols[i]:
                v1 = stats.get(k1, "—")
                v2 = stats.get(k2, "—")
                st.metric(k1, v1)
                st.metric(k2, v2)

        with metric_cols[0]:
            st.metric("交易日数", stats.get("交易日数", "—"))
        with metric_cols[1]:
            st.metric("年化(年)", stats.get("年化(年)", "—"))
        with metric_cols[2]:
            if "基准总收益" in stats:
                st.metric("基准总收益", stats["基准总收益"])
        with metric_cols[3]:
            st.metric("总权重", f"{total_weight:.1f}%")

        # 统计明细表
        stats_df = pd.DataFrame(list(stats.items()), columns=["指标", "数值"])
        st.dataframe(stats_df, use_container_width=True, hide_index=True)

# ═══════════════════════════════════════════════════════
# TAB 4: Brinson 归因
# ═══════════════════════════════════════════════════════
with tab_attribution:
    st.markdown("**Brinson 绩效归因** — 分解收益来源为行业配置效应和个股选择效应")
    attr_start = st.text_input("归因起始", (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"),
                                key="attr_start")
    attr_end = st.text_input("归因结束", datetime.now().strftime("%Y-%m-%d"),
                              key="attr_end")

    if st.button("🔬 执行归因", type="primary", key="calc_attr"):
        with st.spinner("正在计算归因..."):
            attr_df = brinson_attribution(
                pid,
                start_date=attr_start.replace("-", ""),
                end_date=attr_end.replace("-", ""),
            )

        if attr_df.empty:
            st.warning("归因计算失败，数据不足")
            st.stop()

        st.dataframe(attr_df, use_container_width=True, hide_index=True)

        # 选股效应可视化
        fig_attr = px.bar(
            attr_df, x="ts_code", y="选股效应%",
            color="选股效应%",
            color_continuous_scale=["#ff6b6b", "#ffd93d", "#00d4aa"],
            title="个股选股效应",
            labels={"ts_code": "股票", "选股效应%": "选股效应%"},
        )
        fig_attr.update_layout(
            height=400,
            template="plotly_dark",
            xaxis_tickangle=-45,
        )
        st.plotly_chart(fig_attr, use_container_width=True)