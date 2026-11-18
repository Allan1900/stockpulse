"""🌍 国际行情 — 港美股 + 汇率 + 全球指数"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

st.set_page_config(page_title="国际行情", layout="wide")

st.markdown("""
<style>
    .card { background: #1a1a2e; border-radius: 10px; padding: 1rem;
            border: 1px solid #2a2a3a; margin: 0.5rem 0; text-align:center; }
    .big-price { font-size: 1.6rem; font-weight: 700; }
    .price-up { color: #ef4444; }
    .price-down { color: #22c55e; }
    .sub-text { color: #888; font-size: 0.8rem; }
    .stApp { background-color: #0e1117; }
</style>
""", unsafe_allow_html=True)

from engine.realtime import (
    get_us_realtime_quote, get_us_daily,
    get_hk_realtime_quote, get_hk_daily,
    get_forex_realtime, get_global_index_snapshot,
    get_hk_market_snapshot, is_trading_time,
)
from engine.realtime_cache import cached_hk_snapshot, cached_hk_quote

st.title("🌍 国际行情")
st.caption(f"港股 · 美股 · 外汇 · 全球指数 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")

tab_us, tab_hk, tab_fx, tab_global = st.tabs(["🇺🇸 美股", "🇭🇰 港股", "💱 外汇", "🌐 全球指数"])

# ════════════════════ US ════════════════════
with tab_us:
    st.markdown("### 美股实时行情")
    col_sym, col_btn = st.columns([3,1])
    with col_sym:
        symbols_str = st.text_input("输入美股代码 (用逗号分隔)", "AAPL,TSLA,MSFT,GOOGL,AMZN",
                                     label_visibility="collapsed")
    with col_btn:
        refresh = st.button("🔄 刷新", key="us_refresh", use_container_width=True)

    symbols = [s.strip().upper() for s in symbols_str.split(",") if s.strip()]

    cols = st.columns(min(len(symbols), 5))
    for i, sym in enumerate(symbols[:5]):
        with cols[i]:
            q = get_us_realtime_quote(sym)
            if "error" in q:
                st.markdown(f'<div class="card"><div class="sub-text">{sym}</div><div class="big-price" style="color:#888">—</div></div>', unsafe_allow_html=True)
            else:
                pct = q.get("pct_chg",0)
                cls = "price-up" if pct > 0 else "price-down"
                arrow = "▲" if pct > 0 else "▼"
                st.markdown(f'<div class="card"><div class="sub-text">{q["name"]}</div><div class="big-price {cls}">${q["price"]:.2f}</div><div class="{cls}">{arrow} {pct:+.2f}%</div></div>', unsafe_allow_html=True)

    # US Daily charts
    st.markdown("### 美股日线")
    sel_us = st.selectbox("选择股票看日线", symbols, index=0, key="us_daily_select")
    if sel_us:
        with st.spinner("加载日线..."):
            df = get_us_daily(sel_us, 60)
        if df is not None and not df.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df.sort_values("date")["date"],
                y=df.sort_values("date")["close"], mode="lines",
                name=sel_us, line=dict(color="#3b82f6", width=2)))
            fig.update_layout(template="plotly_dark", height=350,
                title=f"{sel_us} 日线", margin=dict(l=20,r=20,t=30,b=20))
            st.plotly_chart(fig, use_container_width=True)

# ════════════════════ HK ════════════════════
with tab_hk:
    st.markdown("### 港股实时行情")
    col_hk, col_hk2 = st.columns([2,1])
    with col_hk:
        hk_codes = st.text_input("输入港股代码 (用逗号分隔)", "00700.HK,00005.HK,09988.HK,00941.HK,00388.HK",
                                   label_visibility="collapsed")
    with col_hk2:
        if st.button("🔄 刷新", key="hk_refresh", use_container_width=True): st.rerun()

    hk_list = [c.strip().upper() for c in hk_codes.split(",") if c.strip()]
    hk_cols = st.columns(min(len(hk_list), 5))
    for i, code in enumerate(hk_list[:5]):
        with hk_cols[i]:
            q = get_hk_realtime_quote(code)
            if "error" in q:
                st.markdown(f'<div class="card"><div class="sub-text">{code}</div><div class="big-price" style="color:#888">—</div></div>', unsafe_allow_html=True)
            else:
                pct = q.get("pct_chg",0)
                cls = "price-up" if pct > 0 else "price-down"
                arrow = "▲" if pct > 0 else "▼"
                st.markdown(f'<div class="card"><div class="sub-text">{q["name"]}</div><div class="big-price {cls}">HK${q["price"]}</div><div class="{cls}">{arrow} {pct:+.2f}%</div></div>', unsafe_allow_html=True)

    st.markdown("### 港股日线")
    sel_hk = st.selectbox("选择股票看日线", hk_list, index=0, key="hk_daily_select")
    if sel_hk:
        with st.spinner("加载日线..."):
            df = get_hk_daily(sel_hk, 60)
        if df is not None and not df.empty:
            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=df.sort_values("date")["date"],
                open=df.sort_values("date")["open"],
                high=df.sort_values("date")["high"],
                low=df.sort_values("date")["low"],
                close=df.sort_values("date")["close"],
                name=sel_hk))
            fig.update_layout(template="plotly_dark", height=400,
                title=f"{sel_hk} 日K", xaxis_rangeslider_visible=False,
                margin=dict(l=20,r=20,t=30,b=20))
            st.plotly_chart(fig, use_container_width=True)

# ════════════════════ Forex ════════════════════
with tab_fx:
    st.markdown("### 外汇实时")
    pairs = ["usdcny", "eurusd", "gbpusd", "usdjpy"]
    fx_cols = st.columns(len(pairs))
    for i, pair in enumerate(pairs):
        with fx_cols[i]:
            fx = get_forex_realtime(pair)
            if "error" in fx:
                st.markdown(f'<div class="card"><div class="sub-text">{pair.upper()}</div><div class="big-price" style="color:#888">—</div></div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="card"><div class="sub-text">{pair.upper()}</div><div class="big-price">{fx["price"]}</div><div class="sub-text">高 {fx.get("high","—")} 低 {fx.get("low","—")}</div></div>', unsafe_allow_html=True)

# ════════════════════ Global Indices ════════════════════
with tab_global:
    st.markdown("### 全球指数 (新浪港股指数)")
    if st.button("🔄 加载全球指数", key="global_idx", use_container_width=True):
        with st.spinner("加载..."):
            idx = get_global_index_snapshot()
        if idx is not None and not idx.empty:
            cols = [c for c in ["代码","名称","最新价","涨跌幅","涨跌额"] if c in idx.columns]
            if "涨跌幅" in idx.columns:
                idx["涨跌幅"] = pd.to_numeric(idx["涨跌幅"], errors="coerce")
                idx["涨跌额"] = pd.to_numeric(idx.get("涨跌额",0), errors="coerce")
            st.dataframe(idx[cols] if cols else idx, use_container_width=True, hide_index=True)

st.caption(f"🌍 国际行情 · 数据来源: 新浪财经 · {datetime.now().strftime('%Y-%m-%d %H:%M')}")