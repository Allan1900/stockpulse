"""宏观数据深度版 — 国内 + FRED(27) + World Bank(9) + 已有国内指标"""
import streamlit as st; import pandas as pd; import plotly.graph_objects as go
from datetime import datetime
st.set_page_config(page_title="宏观数据", layout="wide")
from engine.macro_v2 import get_macro, list_indicators, FRED_SERIES, WORLD_BANK_INDICATORS
from engine.query import sql as _sql

st.markdown("""<style>.stApp{background-color:#0e1117}</style>""", unsafe_allow_html=True)
st.title("宏观数据深度版"); st.caption("国内 + FRED(27指标) + World Bank(9指标)")

# FRED 类别
FRED_CATS = {
    "GDP/增长": ["GDP","GDPC1","INDPRO","TCU","PAYEMS"],
    "通胀": ["CPIAUCSL","CPILFESL","PCEPILFE","T5YIE","T10YIE"],
    "利率": ["FEDFUNDS","DFF","DGS10","DGS2","DGS30","T10Y2Y","BAA10Y"],
    "就业": ["UNRATE","ICSA"],
    "消费/房产": ["RSXFS","UMCSENT","PCE","HOUST"],
    "货币/其他": ["M2SL","WALCL","SP500","DJIA"],
}

tab_domestic, tab_fred, tab_wb = st.tabs(["国内指标", "FRED 美国", "World Bank 全球"])

with tab_domestic:
    st.markdown("### 国内宏观指标")
    indicators = ["cpi","ppi","pmi","gdp","m2","shibor","lpr"]
    sel = st.selectbox("选择指标", indicators, index=0, key="dom_sel")
    days = st.slider("回看天数", 30, 600, 120, key="dom_days")
    df = get_macro(sel, days)
    if df is not None and not df.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["period"], y=df["value"], mode="lines", name=sel.upper(), line=dict(color="#3b82f6", width=2)))
        fig.update_layout(template="plotly_dark", height=350, title=sel.upper(), xaxis_title="日期", yaxis_title="值")
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df.sort_values("period", ascending=False).head(20), hide_index=True, use_container_width=True)

with tab_fred:
    st.markdown("### FRED 美国经济指标 (27项)")
    cat = st.selectbox("选择类别", list(FRED_CATS.keys()), index=0, key="fred_cat")
    series = FRED_CATS[cat]
    sel = st.selectbox("选择指标", series, index=0, format_func=lambda x: f"{x} — {FRED_SERIES.get(x, '')}", key="fred_sel")
    days = st.slider("回看天数", 30, 2000, 500, key="fred_days")
    
    with st.spinner(f"加载 {sel}..."):
        df = get_macro(f"fred_{sel}", days)
    if df is not None and not df.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["period"], y=df["value"], mode="lines", name=FRED_SERIES.get(sel, sel), line=dict(color="#22c55e", width=2)))
        fig.update_layout(template="plotly_dark", height=350, title=f"{FRED_SERIES.get(sel, sel)} ({sel})")
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df.sort_values("period", ascending=False).head(10), hide_index=True, use_container_width=True)
    else:
        st.info("暂无数据，请确认每日更新 cron 已运行")

with tab_wb:
    st.markdown("### World Bank 全球指标 (9项)")
    sel = st.selectbox("选择指标", list(WORLD_BANK_INDICATORS.keys()), index=0,
        format_func=lambda x: f"{WORLD_BANK_INDICATORS.get(x, '')} ({x})", key="wb_sel")
    days = st.slider("回看天数", 10, 50, 30, key="wb_days")
    with st.spinner(f"加载 {WORLD_BANK_INDICATORS.get(sel, sel)}..."):
        df = get_macro(f"wb_{sel}", days)
    if df is not None and not df.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["period"], y=df["value"], mode="lines+markers", name=WORLD_BANK_INDICATORS.get(sel, sel), line=dict(color="#eab308", width=2)))
        fig.update_layout(template="plotly_dark", height=350, title=WORLD_BANK_INDICATORS.get(sel, sel))
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df.sort_values("period", ascending=False).head(10), hide_index=True, use_container_width=True)

st.caption(f"宏观数据深度版 · 数据源: FRED/World Bank/国家统计局 · {datetime.now():%Y-%m-%d}")
