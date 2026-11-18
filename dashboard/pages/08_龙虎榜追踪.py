"""
🏆 龙虎榜追踪 — 对标 Wind 龙虎榜分析

功能:
- 每日龙虎榜排行（净买入/净卖出）
- 个股上榜频率统计
- 营业部活跃度分析
- 上榜原因分类统计
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta

st.set_page_config(page_title="龙虎榜追踪", layout="wide")
st.title("🏆 龙虎榜追踪")
st.caption("对标 Wind 龙虎榜分析功能 · 数据来源: Tushare top_list")

from engine.api_adapter import get_stock_list
from engine.query import sql

# ── 数据加载（首次或缓存） ────────────────────────────
@st.cache_data(ttl=300)
def load_toplist_dates():
    df = sql(None, "SELECT DISTINCT trade_date FROM top_list ORDER BY trade_date DESC")
    return df["trade_date"].tolist() if not df.empty else []

@st.cache_data(ttl=300)
def load_toplist_by_date(day):
    return sql(None,
               "SELECT * FROM top_list WHERE trade_date=%s ORDER BY net_amount DESC",
               params=[day])

@st.cache_data(ttl=300)
def load_toplist_stats():
    """预计算整体统计"""
    return sql(None, """
        SELECT
            COUNT(DISTINCT trade_date) as trading_days,
            COUNT(*) as total_records,
            COUNT(DISTINCT ts_code) as stocks_involved,
            ROUND(AVG(net_amount)::numeric, 2) as avg_net_amount
        FROM top_list
    """)

@st.cache_data(ttl=300)
def load_individual_stats(code):
    """个股龙虎榜统计"""
    return sql(None, """
        SELECT
            ts_code, name,
            COUNT(*) as appearances,
            ROUND(AVG(net_amount)::numeric, 2) as avg_net,
            ROUND(SUM(net_amount)::numeric, 2) as total_net,
            MIN(trade_date) as first_seen,
            MAX(trade_date) as last_seen
        FROM top_list
        WHERE ts_code=%s
        GROUP BY ts_code, name
    """, params=[code])

# ── 侧边栏导航 ──────────────────────────────────────
stocks_df = get_stock_list()

tab_mode = st.radio("查看模式", ["📅 按日期", "📈 按个股", "📊 统计分析"],
                    horizontal=True)

# ═══════════════════════════════════════════════════════
# TAB 1: 按日期查看
# ═══════════════════════════════════════════════════════
if tab_mode == "📅 按日期":
    dates = load_toplist_dates()
    if not dates:
        st.warning("⚠️ 龙虎榜数据正在回填中，请稍后再查看。当前数据为空。")
        st.stop()

    col_d1, col_d2 = st.columns([2, 1])
    with col_d1:
        sel_date = st.selectbox("选择交易日", dates, index=0)
    with col_d2:
        top_n = st.number_input("显示条数", 5, 100, 20, step=5)

    df = load_toplist_by_date(sel_date)
    if df.empty:
        st.info(f"{sel_date} 无龙虎榜数据")
        st.stop()

    # 净买入排行
    st.subheader(f"📋 {sel_date} 龙虎榜 — 净买入排行（前{top_n}）")
    top_buyers = df.head(top_n)
    fig1 = px.bar(top_buyers, x="ts_code", y="net_amount",
                  color="net_amount",
                  color_continuous_scale=["#ff6b6b", "#ffd93d", "#00d4aa"],
                  hover_data=["name", "reason", "l_buy", "l_sell"],
                  labels={"ts_code": "股票", "net_amount": "净额(元)",
                          "name": "名称", "reason": "原因"},
                  title=f"{sel_date} 龙虎榜净买入 TOP{top_n}")
    fig1.update_layout(height=450, template="plotly_dark",
                       xaxis_tickangle=-45)
    st.plotly_chart(fig1, use_container_width=True)

    # 详细数据表
    st.subheader("📄 详细数据")
    display = df[["ts_code", "name", "close", "pct_change", "net_amount",
                  "l_buy", "l_sell", "reason"]].head(50).copy()
    display.columns = ["代码", "名称", "收盘价", "涨跌幅%", "净额(元)",
                        "买入额(元)", "卖出额(元)", "上榜原因"]
    st.dataframe(display, use_container_width=True, hide_index=True)

# ═══════════════════════════════════════════════════════
# TAB 2: 按个股查看
# ═══════════════════════════════════════════════════════
elif tab_mode == "📈 按个股":
    sel_label = st.selectbox(
        "选择股票", options=[f"{r['ts_code']} — {r['name']}"
                            for _, r in stocks_df.iterrows()],
        placeholder="搜索股票", label_visibility="visible")
    code = sel_label.split(" —")[0] if sel_label else ""

    if code:
        stats = load_individual_stats(code)
        if stats.empty:
            st.info(f"{code} 未曾上榜龙虎榜")
        else:
            row = stats.iloc[0]
            col_a, col_b, col_c, col_d = st.columns(4)
            with col_a:
                st.metric("上榜次数", row["appearances"])
            with col_b:
                st.metric("平均净额(万)", f"{row['avg_net']/1e4:.1f}")
            with col_c:
                st.metric("累计净额(万)", f"{row['total_net']/1e4:.1f}")
            with col_d:
                st.metric("首次上榜", row["first_seen"][:10] if row["first_seen"] else "-")

            # 历史龙虎榜明细
            hist = sql(None,
                       "SELECT trade_date, close, pct_change, net_amount, "
                       "l_buy, l_sell, reason "
                       "FROM top_list WHERE ts_code=%s ORDER BY trade_date DESC",
                       params=[code])
            if not hist.empty:
                st.subheader("📜 上榜历史")
                hist_display = hist.copy()
                hist_display["net_amount(万)"] = hist_display["net_amount"] / 1e4
                hist_display["l_buy(万)"] = hist_display["l_buy"] / 1e4
                hist_display["l_sell(万)"] = hist_display["l_sell"] / 1e4
                st.dataframe(
                    hist_display[["trade_date", "pct_change",
                                  "net_amount(万)", "l_buy(万)",
                                  "l_sell(万)", "reason"]],
                    use_container_width=True, hide_index=True)

                # 走向图
                fig_line = px.line(
                    hist.sort_values("trade_date"),
                    x="trade_date", y="net_amount",
                    title=f"{code} 龙虎榜净额时序",
                    markers=True,
                    labels={"trade_date": "日期", "net_amount": "净额(元)"})
                fig_line.update_layout(height=350, template="plotly_dark")
                st.plotly_chart(fig_line, use_container_width=True)

# ═══════════════════════════════════════════════════════
# TAB 3: 统计分析
# ═══════════════════════════════════════════════════════
elif tab_mode == "📊 统计分析":
    stats = load_toplist_stats()
    if stats.empty:
        st.warning("数据正在回填中")
        st.stop()

    row = stats.iloc[0]
    col_a, col_b, col_c, col_d = st.columns(4)
    with col_a: st.metric("交易日数", row["trading_days"])
    with col_b: st.metric("总记录数", f"{row['total_records']:,}")
    with col_c: st.metric("涉及股票", row["stocks_involved"])
    with col_d: st.metric("平均净额(万)", f"{row['avg_net_amount']/1e4:.1f}")

    st.divider()

    # 上榜频率排行
    st.subheader("🏆 最活跃龙虎榜股票")
    freq = sql(None, """
        SELECT ts_code, name, COUNT(*) as cnt,
               ROUND(AVG(net_amount)::numeric, 2) as avg_net
        FROM top_list
        GROUP BY ts_code, name
        ORDER BY cnt DESC
        LIMIT 30
    """)
    if not freq.empty:
        # 构造显示标签：名称 + 代码
        freq["label"] = freq["name"] + " (" + freq["ts_code"].str.split(".").str[0] + ")"

        # 排行表格
        st.subheader("📋 上榜次数排行 TOP30")
        tbl = freq[["label", "cnt", "avg_net"]].copy()
        tbl.columns = ["股票", "上榜次数", "平均净额(万)"]
        tbl["平均净额(万)"] = (tbl["平均净额(万)"] / 1e4).round(1)
        st.dataframe(tbl, use_container_width=True, hide_index=True)

        # 柱状图（显示名称标签）
        fig_freq = px.bar(freq, x="label", y="cnt",
                          color="avg_net",
                          color_continuous_scale="RdYlGn",
                          hover_data=["ts_code", "avg_net"],
                          labels={"label": "股票", "cnt": "上榜次数",
                                  "avg_net": "平均净额"},
                          title="上榜次数 TOP30")
        fig_freq.update_layout(height=400, template="plotly_dark",
                               xaxis_tickangle=-60)
        st.plotly_chart(fig_freq, use_container_width=True)

    # 原因分类
    st.subheader("📂 上榜原因分布")
    reasons = sql(None, """
        SELECT reason, COUNT(*) as cnt
        FROM top_list
        GROUP BY reason
        ORDER BY cnt DESC
        LIMIT 20
    """)
    if not reasons.empty:
        fig_reason = px.pie(reasons, values="cnt", names="reason",
                            title="上榜原因分类",
                            color_discrete_sequence=px.colors.qualitative.Set3)
        fig_reason.update_layout(height=450, template="plotly_dark")
        st.plotly_chart(fig_reason, use_container_width=True)