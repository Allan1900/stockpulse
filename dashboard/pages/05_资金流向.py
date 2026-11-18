"""💰 资金流向分析 — 全市场排行 / 板块矩阵 / 个股时序 / 区间排行"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import numpy as np
from datetime import datetime

st.set_page_config(page_title="资金流向", layout="wide")
st.title("💰 资金流向分析")

from engine.api_adapter import get_stock_list, get_moneyflow_dates, get_moneyflow_by_date, get_moneyflow
from engine.query import sql

stocks_df = get_stock_list()
name_map = dict(zip(stocks_df["ts_code"], stocks_df["name"]))
industries = sorted(stocks_df["industry"].dropna().unique())

col1, col2 = st.columns([1, 2])
with col1:
    top_n = st.slider("排行数量", 10, 50, 20)
with col2:
    view = st.radio("查看模式",
                    ["全市场排行", "板块排行", "个股时序", "区间排行"],
                    horizontal=True)

# ===== 参数选择（在查询按钮之前） =====
dates = get_moneyflow_dates()
if not dates:
    st.warning("资金流数据构建中，稍后再试"); st.stop()

if view == "全市场排行":
    col_a, col_b = st.columns(2)
    with col_a:
        sel_date = st.selectbox("选择日期", dates, index=0)
    with col_b:
        direction = st.radio("方向", ["净流入", "净流出"], horizontal=True)

elif view == "板块排行":
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        sel_industry = st.selectbox("选择板块", industries, index=0)
    with col_b:
        sel_date = st.selectbox("选择日期", dates, index=0)
    with col_c:
        direction = st.radio("方向", ["净流入", "净流出"], horizontal=True)

elif view == "个股时序":
    labels = [f"{r['ts_code']} - {r['name']}" for _, r in stocks_df.iterrows()]
    sel = st.selectbox("选择股票", labels, index=0)
    ts_code = sel.split(" -")[0]
    col_a, col_b = st.columns(2)
    with col_a:
        start = st.text_input("开始", "2025-06-01").replace("-", "")
    with col_b:
        end = st.text_input("结束", datetime.now().strftime("%Y-%m-%d")).replace("-", "")

else:  # 区间排行
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        range_start = st.text_input("区间起始", "2026-01-01").replace("-", "")
    with col_b:
        range_end = st.text_input("区间结束", datetime.now().strftime("%Y-%m-%d")).replace("-", "")
    with col_c:
        range_dir = st.radio("方向", ["净流入", "净流出"], horizontal=True)

# ===== 查询按钮 =====
col_btn, _ = st.columns([1, 5])
with col_btn:
    start_query = st.button("💰 查询", type="primary", use_container_width=True)

if not start_query:
    st.info("👆 选择模式和参数后，点击「查询」加载数据")
    st.stop()

# ===== 执行查询 =====
if view == "全市场排行":
    with st.spinner("加载排行数据..."):
        df = get_moneyflow_by_date(sel_date,
                                   direction="desc" if direction == "净流入" else "asc",
                                   top_n=top_n)
    if not df.empty:
        df["name"] = df["ts_code"].map(name_map)
        df["net_mf_amount"] = df["net_mf_amount"].fillna(0)
        colors = ["#ef5350" if v >= 0 else "#26a69a" for v in df["net_mf_amount"]]
        fig = go.Figure()
        fig.add_trace(go.Bar(y=df["name"][::-1], x=df["net_mf_amount"][::-1]/1e4,
                             orientation="h", marker_color=colors[::-1],
                             text=[f"{v/1e4:.1f}万" for v in df["net_mf_amount"]][::-1],
                             textposition="outside"))
        fig.add_vline(x=0, line_dash="dot", line_color="gray", opacity=0.5)
        fig.update_layout(template="plotly_dark", height=500, margin=dict(l=120,r=50,t=0,b=0),
                          xaxis_title="主力净流入(万元)")
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df[["ts_code","name","net_mf_amount"]], use_container_width=True, hide_index=True)
    else:
        st.warning("暂无数据")

elif view == "板块排行":
    with st.spinner(f"加载 {sel_industry} 板块资金流..."):
        sector_codes = stocks_df[stocks_df["industry"] == sel_industry]["ts_code"].tolist()
        if not sector_codes:
            st.warning("该板块无股票数据"); st.stop()
        codes_str = ",".join([f"'{c}'" for c in sector_codes])
        df_sector = sql("moneyflow",
                        f"SELECT ts_code, trade_date, net_mf_amount FROM moneyflow "
                        f"WHERE trade_date='{sel_date}' AND ts_code IN ({codes_str}) "
                        f"ORDER BY net_mf_amount {'DESC' if direction == '净流入' else 'ASC'}")
        if df_sector.empty:
            st.warning(f"{sel_industry} 板块在 {sel_date} 无资金流数据"); st.stop()
        df_sector = df_sector.head(top_n).copy()

    df_sector["name"] = df_sector["ts_code"].map(name_map)
    df_sector["net_mf_amount"] = df_sector["net_mf_amount"].fillna(0)

    st.subheader(f"🏭 {sel_industry} — {sel_date} 资金流向排行")
    colors = ["#ef5350" if v >= 0 else "#26a69a" for v in df_sector["net_mf_amount"]]
    fig = go.Figure()
    fig.add_trace(go.Bar(y=df_sector["name"][::-1], x=df_sector["net_mf_amount"][::-1]/1e4,
                         orientation="h", marker_color=colors[::-1],
                         text=[f"{v/1e4:.1f}万" for v in df_sector["net_mf_amount"]][::-1],
                         textposition="outside"))
    fig.add_vline(x=0, line_dash="dot", line_color="gray", opacity=0.5)
    fig.update_layout(template="plotly_dark", height=450, margin=dict(l=120,r=50,t=0,b=0),
                      xaxis_title="主力净流入(万元)")
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(df_sector[["ts_code","name","net_mf_amount"]],
                 use_container_width=True, hide_index=True)

    # 板块资金矩阵（热力图）
    st.subheader(f"📊 {sel_industry} 资金矩阵（近10日）")
    idx = dates.index(sel_date)
    recent_dates = dates[max(0, idx-9):idx+1]
    codes_str = ",".join([f"'{c}'" for c in sector_codes])
    date_str = ",".join([f"'{d}'" for d in recent_dates])
    with st.spinner("加载板块资金矩阵..."):
        all_mat = sql("moneyflow",
                      f"SELECT ts_code, trade_date, net_mf_amount FROM moneyflow "
                      f"WHERE trade_date IN ({date_str}) AND ts_code IN ({codes_str})")
    if not all_mat.empty:
        all_mat["name"] = all_mat["ts_code"].map(name_map)
        all_mat["net_mf_amount"] = all_mat["net_mf_amount"].fillna(0)
        top_codes = df_sector["ts_code"].tolist()
        all_mat = all_mat[all_mat["ts_code"].isin(top_codes)]
        pivot = all_mat.pivot_table(index="name", columns="trade_date",
                                    values="net_mf_amount", aggfunc="sum")
        pivot["_total"] = pivot.sum(axis=1)
        pivot = pivot.sort_values("_total", ascending=False).drop(columns="_total")
        pivot = pivot.head(top_n)
        fig_h = px.imshow(pivot.values,
                          x=[f"{d[4:6]}/{d[6:8]}" for d in pivot.columns],
                          y=pivot.index,
                          color_continuous_scale=["#26a69a", "#263238", "#ef5350"],
                          aspect="auto",
                          labels=dict(x="日期", y="股票", color="净流入"))
        fig_h.update_layout(template="plotly_dark", height=80 + 30 * len(pivot),
                            margin=dict(l=100, r=20, t=0, b=0))
        fig_h.update_traces(text=[f"{v/1e4:.0f}" if abs(v) > 1e4 else ""
                                  for v in pivot.values.flat],
                            texttemplate="%{text}", textfont=dict(size=9))
        st.plotly_chart(fig_h, use_container_width=True)
        csv = all_mat.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 下载板块资金矩阵", csv,
                           f"{sel_industry}_资金矩阵_{recent_dates[0]}_{recent_dates[-1]}.csv",
                           "text/csv")
    else:
        st.info("资金矩阵数据不足")

elif view == "个股时序":
    with st.spinner("加载资金流数据..."):
        df = get_moneyflow(ts_code, start, end)
    if df.empty:
        st.warning("无资金流数据"); st.stop()

    x = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    fig = go.Figure()
    for col, c, l in [("net_mf_amount", "#ef5350", "主力净流入"),
                       ("buy_lg_vol", "#ffd740", "大单买入"),
                       ("buy_sm_vol", "#29b6f6", "小单买入")]:
        if col in df.columns:
            fig.add_trace(go.Scatter(x=x, y=df[col], mode="lines", name=l,
                                     line=dict(color=c, width=1.5)))
    fig.add_hline(y=0, line_dash="dot", line_color="gray", opacity=0.3)
    fig.update_layout(template="plotly_dark", height=400, hovermode="x unified",
                      legend=dict(orientation="h", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig, use_container_width=True)

    df["cum"] = df["net_mf_amount"].fillna(0).cumsum()
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=x, y=df["cum"], mode="lines", fill="tozeroy",
                              name="累计净流入", line=dict(color="#ef5350", width=2)))
    fig2.update_layout(template="plotly_dark", height=250)
    st.plotly_chart(fig2, use_container_width=True)

    with st.expander("📋 数据"):
        st.dataframe(df, use_container_width=True, height=400)
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 下载 CSV", csv, f"{ts_code}_moneyflow.csv", "text/csv")

else:  # 区间排行 — 新增功能
    with st.spinner(f"计算 {range_start} ~ {range_end} 区间累计资金流排行..."):
        df_range = sql("moneyflow",
                       f"SELECT ts_code, SUM(net_mf_amount) AS cum_net_mf "
                       f"FROM moneyflow "
                       f"WHERE trade_date >= '{range_start}' AND trade_date <= '{range_end}' "
                       f"GROUP BY ts_code "
                       f"ORDER BY cum_net_mf {'DESC' if range_dir == '净流入' else 'ASC'} "
                       f"LIMIT {top_n}")
    if df_range.empty:
        st.warning("区间无资金流数据"); st.stop()

    df_range["name"] = df_range["ts_code"].map(name_map)
    df_range["cum_net_mf"] = df_range["cum_net_mf"].fillna(0)

    st.subheader(f"📊 区间资金排行: {range_start} ~ {range_end}")
    st.caption(f"累计主力净流入 TOP{top_n}（{'净流入 ↑' if range_dir == '净流入' else '净流出 ↓'}）")

    colors = ["#ef5350" if v >= 0 else "#26a69a" for v in df_range["cum_net_mf"]]
    fig = go.Figure()
    fig.add_trace(go.Bar(y=df_range["name"][::-1], x=df_range["cum_net_mf"][::-1]/1e4,
                         orientation="h", marker_color=colors[::-1],
                         text=[f"{v/1e4:+.1f}万" for v in df_range["cum_net_mf"]][::-1],
                         textposition="outside"))
    fig.add_vline(x=0, line_dash="dot", line_color="gray", opacity=0.5)
    fig.update_layout(template="plotly_dark", height=500, margin=dict(l=120,r=50,t=0,b=0),
                      xaxis_title=f"累计主力净流入(万元) / {range_start}-{range_end}")
    st.plotly_chart(fig, use_container_width=True)

    # 带百分比列的详细表
    total_abs = df_range["cum_net_mf"].abs().sum() or 1
    df_range["占比%"] = (df_range["cum_net_mf"].abs() / total_abs * 100).round(1)
    st.dataframe(df_range[["ts_code", "name", "cum_net_mf", "占比%"]],
                 column_config={
                     "cum_net_mf": st.column_config.NumberColumn("累计净流入", format="%.2f"),
                     "占比%": st.column_config.NumberColumn("占比%", format="%.1f%%"),
                 },
                 use_container_width=True, hide_index=True)

    csv = df_range.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📥 下载区间排行", csv,
                       f"区间资金排行_{range_start}_{range_end}.csv", "text/csv")