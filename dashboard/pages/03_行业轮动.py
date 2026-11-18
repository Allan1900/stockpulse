"""🏭 行业轮动分析 — 多周期排行 + 轮动热图 + 成分股穿透"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime

st.set_page_config(page_title="行业轮动", layout="wide")
st.title("🏭 行业轮动分析")

from engine.api_adapter import get_stock_list
from engine.query import query

stocks_df = get_stock_list()
industries = sorted(stocks_df["industry"].dropna().unique())

col_period, col_top, _ = st.columns([2, 1, 2])
with col_period:
    period = st.selectbox("分析周期", ["近1月", "近3月", "近6月", "年初至今", "自定义"], index=2)
with col_top:
    top_n = st.slider("显示前N", 5, 30, 10)

now = datetime.now()
period_map = {
    "近1月": (now - pd.DateOffset(months=1)).strftime("%Y%m%d"),
    "近3月": (now - pd.DateOffset(months=3)).strftime("%Y%m%d"),
    "近6月": (now - pd.DateOffset(months=6)).strftime("%Y%m%d"),
    "年初至今": f"{now.year}0101",
}
if period == "自定义":
    col_a, col_b = st.columns(2)
    start = col_a.text_input("开始", "2026-01-01").replace("-", "")
    end = col_b.text_input("结束", now.strftime("%Y-%m-%d")).replace("-", "")
else:
    start = period_map[period]
    end = now.strftime("%Y%m%d")

col_query, _ = st.columns([1, 5])
with col_query:
    run = st.button("🏭 开始分析", type="primary", use_container_width=True)

if not run:
    st.info("👆 选择周期和排行数量后点击「开始分析」")
    st.stop()

with st.spinner("计算行业表现..."):
    df = query(fields="ts_code,trade_date,close,pct_chg,vol",
               start_date=start, end_date=end)

if df.empty:
    st.warning("无数据"); st.stop()

ind_map = dict(zip(stocks_df["ts_code"], stocks_df["industry"]))
name_map = dict(zip(stocks_df["ts_code"], stocks_df["name"]))
df["industry"] = df["ts_code"].map(ind_map)
df["name"] = df["ts_code"].map(name_map)
df = df.dropna(subset=["industry"])

tab1, tab2, tab3 = st.tabs(["🏆 行业排行", "🗺 轮动热图", "🔍 成分股穿透"])

with tab1:
    ind_perf = []
    for ind, grp in df.groupby("industry"):
        by_stock = grp.groupby("ts_code")
        rets = []
        for _, sub in by_stock:
            if len(sub) >= 2:
                rets.append((sub["close"].iloc[-1] / sub["close"].iloc[0] - 1) * 100)
        if rets:
            ind_perf.append({
                "行业": ind, "股票数": len(rets),
                "涨幅中位数": np.median(rets),
                "涨幅均值": np.mean(rets),
                "涨幅标准差": np.std(rets),
            })
    ind_df = pd.DataFrame(ind_perf).sort_values("涨幅中位数", ascending=False).head(top_n)
    display = ind_df.copy()
    display["涨幅中位数"] = display["涨幅中位数"].map("{:+.2f}%".format)
    display["涨幅均值"] = display["涨幅均值"].map("{:+.2f}%".format)
    display["涨幅标准差"] = display["涨幅标准差"].map("{:.2f}%".format)
    st.dataframe(display, use_container_width=True, hide_index=True)

    fig = go.Figure()
    vals = ind_df["涨幅中位数"].tolist()[::-1]
    labs = ind_df["行业"].tolist()[::-1]
    colors = ["#ef5350" if v >= 0 else "#26a69a" for v in vals]
    fig.add_trace(go.Bar(y=labs, x=vals, orientation="h", marker_color=colors,
                         text=[f"{v:+.2f}%" for v in vals], textposition="outside"))
    fig.add_vline(x=0, line_dash="dot", line_color="gray", opacity=0.5)
    fig.update_layout(template="plotly_dark", height=500,
                      margin=dict(l=150, r=50, t=0, b=0),
                      xaxis_title=f"涨幅中位数 % ({period})")
    st.plotly_chart(fig, use_container_width=True)

with tab2:
    freq2 = st.radio("频率", ["周度", "月度"], horizontal=True, index=0)
    st.subheader(f"🗺 行业{freq2}轮动热图（近12期）")
    df_h = query(fields="ts_code,trade_date,close",
                 start_date=start, end_date=end)
    if not df_h.empty:
        df_h["industry"] = df_h["ts_code"].map(ind_map)
        if freq2 == "周度":
            iso = pd.to_datetime(df_h["trade_date"], format="%Y%m%d").dt.isocalendar()
            df_h["period"] = iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
        else:
            df_h["period"] = pd.to_datetime(df_h["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m")
        heat_data = []
        for ind, grp in df_h.groupby("industry"):
            for per, sub in grp.groupby("period"):
                by_code = sub.groupby("ts_code")
                rets = []
                for _, s in by_code:
                    if len(s) >= 2:
                        rets.append((s["close"].iloc[-1] / s["close"].iloc[0] - 1) * 100)
                if rets:
                    heat_data.append({"行业": ind, "周期": per, "收益率": np.median(rets)})
        if heat_data:
            pivot = pd.DataFrame(heat_data).pivot_table(
                index="行业", columns="周期", values="收益率")
            top_inds = ind_df["行业"].head(top_n).tolist()
            pivot = pivot.loc[[i for i in top_inds if i in pivot.index]]
            pivot = pivot.iloc[:, -min(12, pivot.shape[1]):]
            fig = px.imshow(pivot, aspect="auto",
                            color_continuous_scale=["#26a69a","#263238","#ef5350"],
                            labels=dict(x=freq2, y="行业", color="收益率%"))
            fig.update_layout(template="plotly_dark", height=600,
                              xaxis=dict(tickangle=-45))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("数据不足")
    else:
        st.info("无数据")

with tab3:
    sel_ind = st.selectbox("选择行业", industries, index=None, placeholder="搜索行业...")
    if sel_ind:
        ind_stocks = stocks_df[stocks_df["industry"] == sel_ind]
        codes = ind_stocks["ts_code"].head(50).tolist()
        perf = query(stocks=codes, fields="ts_code,close",
                     start_date=start, end_date=end)
        if not perf.empty:
            rows = []
            for code, grp in perf.groupby("ts_code"):
                if len(grp) >= 2:
                    ret = (grp["close"].iloc[-1] / grp["close"].iloc[0] - 1) * 100
                    rows.append({"代码": code, "名称": name_map.get(code, ""),
                                 "涨幅": f"{ret:+.2f}%"})
            st.dataframe(pd.DataFrame(rows).sort_values("涨幅", ascending=False),
                         use_container_width=True, hide_index=True)
            ret_vals = [float(r["涨幅"].replace("%", "")) for r in rows]
            fig_hist = px.histogram(x=ret_vals, nbins=30,
                                    labels={"x": "涨幅%", "y": "股票数"},
                                    title=f"{sel_ind} 成分股涨幅分布")
            fig_hist.update_layout(template="plotly_dark", height=300)
            st.plotly_chart(fig_hist, use_container_width=True)