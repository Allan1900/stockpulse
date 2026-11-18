"""🎯 智能筛选引擎 — 行情 × 估值 × 财务 × 技术指标条件"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from datetime import datetime

st.set_page_config(page_title="筛选引擎", layout="wide")
st.title("🎯 智能筛选引擎")

from engine.api_adapter import get_stock_list, get_daily_basic
from engine.query import query
from engine.indicators import calc_all_indicators, calc_obv

stocks_df = get_stock_list()
industries = sorted(stocks_df["industry"].dropna().unique())

st.subheader("⚙️ 筛选条件")

# 条件行 1: 行情 + 技术指标
col_a, col_b, col_c = st.columns(3)
with col_a:
    st.markdown("**📊 行情条件**")
    min_price = st.number_input("最低股价", 0.0, 1000.0, 0.0, 1.0, key="min_p")
    max_price = st.number_input("最高股价", 0.0, 1000.0, 1000.0, 1.0, key="max_p")
    min_amt = st.number_input("最低日均成交额(亿)", 0.0, 1000.0, 0.0, 0.5, key="min_a")

with col_b:
    st.markdown("**💹 估值条件**")
    min_pe = st.number_input("最低 PE-TTM", 0.0, 200.0, 0.0, 1.0, key="min_pe")
    max_pe = st.number_input("最高 PE-TTM", 0.0, 200.0, 200.0, 1.0, key="max_pe")
    max_pb = st.number_input("最高 PB", 0.0, 50.0, 50.0, 0.5, key="max_pb")

with col_c:
    st.markdown("**🏭 基础条件**")
    sel_industry = st.multiselect("行业", industries)
    min_ret = st.number_input("最低区间涨幅%", -100.0, 200.0, -100.0, 5.0, key="min_r")
    max_ret = st.number_input("最高区间涨幅%", -100.0, 200.0, 200.0, 5.0, key="max_r")

# 条件行 2: 技术指标
col_d, col_e, col_f = st.columns(3)
with col_d:
    st.markdown("**📈 技术指标**")
    rsi_min = st.slider("RSI(6) 最低", 0, 100, 0, key="rsi_min")
    rsi_max = st.slider("RSI(6) 最高", 0, 100, 100, key="rsi_max")
    macd_state = st.selectbox("MACD 状态", ["不限", "多头(DIF>DEA)", "空头(DIF<DEA)", "金叉↑", "死叉↓"], index=0)

with col_e:
    st.markdown("**📦 布林带 & 量能**")
    boll_pos = st.selectbox("布林带位置", ["不限", "上轨突破", "上轨以上", "中轨以上", "中轨以下", "下轨以下"], index=0)
    vol_ratio_min = st.number_input("最低量比(vol/MA5)", 0.0, 10.0, 0.0, 0.1, key="vr_min")

with col_f:
    st.markdown("**📅 区间设置**")
    perf_start = st.text_input("区间开始", "2026-01-01").replace("-", "")
    perf_end = st.text_input("区间结束", datetime.now().strftime("%Y-%m-%d")).replace("-", "")

col_query, _ = st.columns([1, 5])
with col_query:
    run = st.button("🔍 执行筛选", type="primary", use_container_width=True)

if not run:
    st.info("👆 设置筛选条件后点击「执行筛选」")
    st.markdown("""
    **示例场景:**
    - 🟢 **低估蓝筹** — PE 10~20, PB<2, 成交额>5亿, RSI>30
    - 🔴 **强势突破** — MACD金叉, RSI(6) 50~80, 布林中轨以上, 量比>1.2
    - 🟡 **超跌反弹** — PE<15, 区间涨幅<0, RSI<30, 布林下轨以下
    """)
    st.stop()

with st.spinner("正在全市场扫描..."):
    candidates = stocks_df.copy()
    if sel_industry:
        candidates = candidates[candidates["industry"].isin(sel_industry)]

    codes = candidates["ts_code"].head(500).tolist()
    if not codes:
        st.warning("无匹配"); st.stop()

    df = query(stocks=codes, fields="ts_code,trade_date,close,open,high,low,vol,amount,pct_chg",
               start_date=perf_start, end_date=perf_end)
    if df.empty:
        st.warning("行情数据为空"); st.stop()

    # 计算技术指标
    df_ind = df.groupby("ts_code", group_keys=False).apply(calc_all_indicators)
    df_ind = df_ind.groupby("ts_code", group_keys=False).apply(calc_obv)

    # 获取最新一天的数据
    last = df_ind.groupby("ts_code").last().reset_index()

    # 区间涨跌幅
    first = df.groupby("ts_code").first().reset_index()
    last_close = last[["ts_code", "close"]].rename(columns={"close": "close_last"})
    first_close = first[["ts_code", "close"]].rename(columns={"close": "close_first", "trade_date": "date_first"})
    merged = last.merge(first_close, on="ts_code")
    merged["ret"] = (merged["close_last"] / merged["close_first"] - 1) * 100
    merged["avg_amt"] = df.groupby("ts_code")["amount"].mean().values / 1e5

    # 估值数据
    df_basic = get_daily_basic(codes, perf_start, perf_end) if codes else pd.DataFrame()
    if not df_basic.empty:
        basic_last = df_basic.groupby("ts_code").last().reset_index()
        merged = merged.merge(basic_last[["ts_code", "pe_ttm", "pb"]], on="ts_code", how="left")

    # 量比
    def calc_vol_ratio(grp):
        avg5 = grp["vol"].rolling(5).mean()
        return grp["vol"].iloc[-1] / avg5.iloc[-1] if not pd.isna(avg5.iloc[-1]) else 0
    vol_ratios = df.groupby("ts_code").apply(calc_vol_ratio).reset_index()
    vol_ratios.columns = ["ts_code", "vol_ratio"]
    merged = merged.merge(vol_ratios, on="ts_code", how="left")

    # === 应用所有筛选条件 ===
    mask = pd.Series([True] * len(merged))
    # 行情
    mask &= (merged["close_last"] >= min_price) & (merged["close_last"] <= max_price)
    if min_amt > 0:
        mask &= (merged["avg_amt"] >= min_amt)
    # 涨幅
    mask &= (merged["ret"] >= min_ret) & (merged["ret"] <= max_ret)
    # 估值
    if "pe_ttm" in merged.columns:
        mask &= (merged["pe_ttm"].fillna(0) >= min_pe) & (merged["pe_ttm"].fillna(999) <= max_pe)
        mask &= (merged["pb"].fillna(0) <= max_pb)
    # 技术指标
    mask &= (merged.get("RSI6", 50).fillna(50) >= rsi_min) & (merged.get("RSI6", 50).fillna(50) <= rsi_max)
    # MACD 状态
    if macd_state == "多头(DIF>DEA)":
        mask &= (merged.get("MACD_DIF", 0).fillna(0) > merged.get("MACD_DEA", 0).fillna(0))
    elif macd_state == "空头(DIF<DEA)":
        mask &= (merged.get("MACD_DIF", 0).fillna(0) < merged.get("MACD_DEA", 0).fillna(0))
    elif macd_state == "金叉↑":
        mask &= (merged.get("MACD_DIF", 0).fillna(0) > merged.get("MACD_DEA", 0).fillna(0)) & \
                (merged.get("MACD_HIST", 0).fillna(0) > 0)
    elif macd_state == "死叉↓":
        mask &= (merged.get("MACD_DIF", 0).fillna(0) < merged.get("MACD_DEA", 0).fillna(0)) & \
                (merged.get("MACD_HIST", 0).fillna(0) < 0)
    # 布林带位置
    if boll_pos == "上轨突破":
        mask &= (merged.get("close_last", 0) >= merged.get("BOLL_UP", 99999).fillna(99999))
    elif boll_pos == "上轨以上":
        mask &= (merged.get("close_last", 0) >= merged.get("BOLL_MID", 0).fillna(0))
    elif boll_pos == "中轨以上":
        mask &= (merged.get("close_last", 0) >= merged.get("BOLL_MID", 0).fillna(0)) & \
                (merged.get("close_last", 0) < merged.get("BOLL_UP", 99999).fillna(99999))
    elif boll_pos == "中轨以下":
        mask &= (merged.get("close_last", 0) <= merged.get("BOLL_MID", 99999).fillna(99999))
    elif boll_pos == "下轨以下":
        mask &= (merged.get("close_last", 0) <= merged.get("BOLL_DN", 99999).fillna(99999))
    # 量比
    if vol_ratio_min > 0:
        mask &= (merged.get("vol_ratio", 0).fillna(0) >= vol_ratio_min)

    results = merged[mask].copy()

st.subheader(f"🎯 筛选结果: {len(results)} 只")
if results.empty:
    st.warning("无结果，请放宽条件"); st.stop()

display = results[["ts_code", "close_last", "ret", "avg_amt"]].copy()
display.columns = ["代码", "最新价", "区间涨幅%", "日均成交额(亿)"]
display["名称"] = display["代码"].map(dict(zip(stocks_df["ts_code"], stocks_df["name"])))
display["行业"] = display["代码"].map(dict(zip(stocks_df["ts_code"], stocks_df["industry"])))
if "pe_ttm" in results.columns:
    display["PE-TTM"] = results["pe_ttm"].round(1)
if "pb" in results.columns:
    display["PB"] = results["pb"].round(2)
if "RSI6" in results.columns:
    display["RSI(6)"] = results["RSI6"].round(1)
if "vol_ratio" in results.columns:
    display["量比"] = results["vol_ratio"].round(2)
display = display.sort_values("区间涨幅%", ascending=False)

st.dataframe(display, use_container_width=True, hide_index=True)
csv = display.to_csv(index=False).encode("utf-8-sig")
st.download_button("📥 下载结果", csv, f"筛选_{perf_start}_{perf_end}.csv", "text/csv")

col_c1, col_c2 = st.columns(2)
with col_c1:
    fig = px.histogram(display["区间涨幅%"], nbins=30, title="涨幅分布",
                       labels={"value": "涨幅%", "count": "股票数"})
    fig.update_layout(template="plotly_dark", height=250)
    st.plotly_chart(fig, use_container_width=True)
with col_c2:
    cnt = display["行业"].value_counts().head(10)
    fig = px.bar(x=cnt.values, y=cnt.index, orientation="h", title="行业分布",
                 labels={"x": "股票数", "y": ""})
    fig.update_layout(template="plotly_dark", height=250)
    st.plotly_chart(fig, use_container_width=True)