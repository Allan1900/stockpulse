"""
📡 实时行情 — 交易时段走实时API, 盘后走PG

功能:
  - 实时大盘 (4大指数: 上证/深证/创业板/科创50) → 🔴LIVE / ⚫CLOSED
  - 个股实时查询 (新浪直连, 毫秒级)
  - 全市场快照 (腾讯, 排序/筛选)
  - 快速搜索+自选
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

st.set_page_config(page_title="实时行情", layout="wide")

st.markdown("""
<style>
    .live-badge { display: inline-block; padding: 2px 12px; border-radius: 12px;
                  font-size: 0.8rem; font-weight: 600; margin-left: 8px; }
    .live-on { background: #22c55e; color: #000; }
    .live-off { background: #64748b; color: #fff; }
    .price-up { color: #ef4444; font-weight: 700; }
    .price-down { color: #22c55e; font-weight: 700; }
    .price-flat { color: #94a3b8; }
    .card { background: #1a1a2e; border-radius: 10px; padding: 1rem;
            border: 1px solid #2a2a3a; }
    .card h3 { margin: 0 0 0.5rem 0; color: #f0f2f6; font-size: 1rem; }
    .big-price { font-size: 1.8rem; font-weight: 700; margin: 0; }
    .sub-text { color: #888; font-size: 0.8rem; }
    .stApp { background-color: #0e1117; }
</style>
""", unsafe_allow_html=True)

from engine.realtime import (
    is_trading_time, get_realtime_quote,
    get_market_snapshot, get_market_overview,
    hybrid_quote,
)
from engine.api_adapter import get_stock_list
from engine.query import sql as _sql

# ════════════════════════════════════════════════════════════════
# 实时状态头
# ════════════════════════════════════════════════════════════════
in_session = is_trading_time()
now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

col_title, col_status = st.columns([3, 1])
with col_title:
    badge_class = "live-on" if in_session else "live-off"
    badge_text = "🔴 LIVE" if in_session else "⚫ CLOSED"
    st.markdown(
        f"## 📡 实时行情 <span class='live-badge {badge_class}'>{badge_text}</span>",
        unsafe_allow_html=True,
    )
with col_status:
    st.caption(f"更新: {now_str}")
    if st.button("🔄 刷新", use_container_width=True, key="refresh_btn"):
        st.rerun()

st.caption(
    "交易时段走新浪/腾讯实时API · 盘后走PG数据库" if in_session
    else "盘后模式 — 数据来自PG数据库 · 开盘后自动切换实时通道"
)

# ════════════════════════════════════════════════════════════════
# Tab 1: 大盘概览
# ════════════════════════════════════════════════════════════════
tab_overview, tab_individual, tab_snapshot = st.tabs(["📊 大盘概览", "🔍 个股实时", "📋 全市场快照"])

with tab_overview:
    st.markdown("### 四大指数实时行情")

    overview = get_market_overview()
    df_idx = overview["data"]
    source = overview["source"]

    if df_idx is not None and not df_idx.empty:
        cols = st.columns(4)
        for i, (_, row) in enumerate(df_idx.iterrows()):
            with cols[i]:
                pct = row.get("涨跌幅", 0)
                pct_cls = "price-up" if pct > 0 else ("price-down" if pct < 0 else "price-flat")
                arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "—")
                st.markdown(f"""
                <div class="card" style="text-align:center;">
                    <h3>{row.get('指数', '')}</h3>
                    <div class="big-price {pct_cls}">{row.get('最新价', 0):.2f}</div>
                    <div class="{pct_cls}">{arrow} {pct:+.2f}%</div>
                    <div class="sub-text">
                        今开 {row.get('今开', 0):.2f} ·
                        高 {row.get('最高', 0):.2f} ·
                        低 {row.get('最低', 0):.2f}
                    </div>
                    <div class="sub-text">
                        成交 {row.get('成交额(亿)', 0):.0f}亿
                    </div>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.warning("暂无指数数据")

    # 全市场涨跌分布
    st.markdown("### 全市场涨跌分布")

    if in_session:
        snap = get_market_snapshot()
    else:
        snap = _sql(None, """
            SELECT ts_code, close, pct_chg FROM daily
            WHERE trade_date = (SELECT MAX(trade_date) FROM daily)
        """)

    if snap is not None and not snap.empty:
        col = "pct_chg" if not in_session else "zdf"
        if col not in snap.columns:
            col = snap.columns[snap.columns.str.contains("pct|zdf|change")][0]

        pct_vals = pd.to_numeric(snap[col], errors="coerce").dropna()
        up = (pct_vals > 0).sum()
        down = (pct_vals < 0).sum()
        flat = (pct_vals == 0).sum()

        m_col1, m_col2, m_col3, m_col4 = st.columns(4)
        with m_col1:
            st.metric("📈 上涨", f"{up} 家", delta_color="off")
        with m_col2:
            st.metric("📉 下跌", f"{down} 家", delta_color="off")
        with m_col3:
            st.metric("⚪ 平盘", f"{flat} 家")
        with m_col4:
            total = up + down + flat
            ratio = round(up / down, 2) if down > 0 else "—"
            st.metric("📊 涨跌比", f"{ratio}")

        # 涨跌分布直方图
        fig = go.Figure()
        fig.add_trace(go.Histogram(
            x=pct_vals,
            nbinsx=50,
            marker_color="#3b82f6",
            name="涨跌幅分布",
        ))
        fig.add_vline(x=0, line_dash="dash", line_color="#ef4444", line_width=1)
        fig.update_layout(
            template="plotly_dark", height=300,
            title="全市场涨跌幅分布",
            xaxis_title="涨跌幅%",
            yaxis_title="股票数",
            margin=dict(l=20, r=20, t=40, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("暂无全市场数据")

# ════════════════════════════════════════════════════════════════
# Tab 2: 个股实时
# ════════════════════════════════════════════════════════════════
with tab_individual:
    st.markdown("### 🔍 个股实时行情")
    st.caption("输入股票代码或名称，毫秒级实时查询")

    stocks_df = get_stock_list()
    labels = [f"{r['ts_code']} - {r['name']}" for _, r in stocks_df.iterrows()]

    col_search, col_code = st.columns([3, 1])
    with col_search:
        sel = st.selectbox("选择股票", labels, index=0, key="rt_stock",
                           label_visibility="collapsed")
    with col_code:
        if st.button("🔍 查询", type="primary", use_container_width=True, key="btn_rt"):
            pass

    ts_code = sel.split(" -")[0]

    # 自动查询
    with st.spinner("获取实时数据…"):
        quote = hybrid_quote(ts_code)

    if "error" in quote:
        st.error(quote["error"])
    else:
        name = quote.get("name", ts_code)
        src = quote.get("source", "?")

        # 指标卡
        pct = quote.get("pct_chg", 0)
        pct_cls = "price-up" if pct > 0 else ("price-down" if pct < 0 else "price-flat")
        arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "—")

        cols = st.columns(5)
        with cols[0]:
            st.markdown(f"""
            <div class="card" style="text-align:center;">
                <div class="sub-text">{name}</div>
                <div class="big-price {pct_cls}">{quote.get('price', 0):.2f}</div>
                <div class="{pct_cls}">{arrow} {pct:+.2f}%</div>
            </div>
            """, unsafe_allow_html=True)

        with cols[1]:
            st.metric("今开", f"{quote.get('open', 0):.2f}",
                      f"昨收 {quote.get('yest_close', 0):.2f}")
        with cols[2]:
            st.metric("最高", f"{quote.get('high', 0):.2f}",
                      f"最低 {quote.get('low', 0):.2f}")
        with cols[3]:
            vol = quote.get('volume', 0)
            st.metric("成交量", f"{vol/1e4:.0f}万手" if vol > 1e4 else f"{vol:.0f}手")
        with cols[4]:
            amt = quote.get('amount', 0)
            st.metric("成交额", f"{amt/1e8:.2f}亿" if amt > 1e8 else f"{amt:.0f}元")

        st.caption(f"数据来源: {'🔴 实时' if src == 'sina_realtime' else '📀 PG数据库'} · {quote.get('datetime', '')}")

        # 买五卖五档位 (如果有)
        bid = quote.get("bid", 0)
        ask = quote.get("ask", 0)
        if bid > 0 or ask > 0:
            col_b, col_a = st.columns(2)
            with col_b:
                st.info(f"📥 买一: {bid:.2f}")
            with col_a:
                st.info(f"📤 卖一: {ask:.2f}")

        # 当日分时图
        if in_session:
            st.markdown("### 当日分时图")
            from engine.realtime import get_intraday_minutes
            minutes = get_intraday_minutes(ts_code)
            if minutes is not None and not minutes.empty:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=pd.to_datetime(minutes["day"]),
                    y=minutes["close"],
                    mode="lines",
                    name="分时价",
                    line=dict(color="#3b82f6", width=2),
                    fill='tozeroy',
                    fillcolor='rgba(59,130,246,0.1)',
                ))
                fig.update_layout(
                    template="plotly_dark", height=350,
                    title=f"{name} 当日分时",
                    margin=dict(l=20, r=20, t=30, b=20),
                    hovermode="x unified",
                )
                st.plotly_chart(fig, use_container_width=True)

# ════════════════════════════════════════════════════════════════
# Tab 3: 全市场快照
# ════════════════════════════════════════════════════════════════
with tab_snapshot:
    st.markdown("### 📋 全市场快照")
    st.caption("实时全市场排序（腾讯接口 ~6s, 27字段）")

    if st.button("📥 加载全市场快照", type="primary", use_container_width=True, key="btn_snap"):
        with st.spinner("获取全市场实时数据 (~6s)…"):
            snap = get_market_snapshot()

        if snap is not None and not snap.empty:
            st.success(f"加载完成: {len(snap)} 只股票")

            # 排序选择
            sort_by = st.selectbox("排序方式", [
                "涨跌幅 ↓", "涨跌幅 ↑", "成交额 ↓", "成交量 ↓",
                "涨幅榜", "跌幅榜", "主力净流入 ↓", "换手率 ↓",
            ], key="sort_mode")

            df_view = snap.copy()

            # 列名映射
            col_zdf = "zdf" if "zdf" in df_view.columns else "pct_chg"
            col_vol = "volume" if "volume" in df_view.columns else "vol"
            col_turn = "turnover" if "turnover" in df_view.columns else "amount"
            col_name = "name" if "name" in df_view.columns else "code"

            df_view["最新价"] = df_view.get("zxj", df_view.get("close", 0))
            df_view["涨跌幅"] = pd.to_numeric(df_view[col_zdf], errors="coerce")
            df_view["成交额(亿)"] = (pd.to_numeric(df_view[col_turn], errors="coerce") / 1e8).round(2)
            df_view["成交量(万手)"] = (pd.to_numeric(df_view[col_vol], errors="coerce") / 1e4).round(2)

            if "hsl" in df_view.columns:
                df_view["换手率%"] = pd.to_numeric(df_view["hsl"], errors="coerce")
            if "zljlr" in df_view.columns:
                df_view["主力净流入(万)"] = (pd.to_numeric(df_view["zljlr"], errors="coerce")).round(2)

            if sort_by == "涨跌幅 ↓":
                df_disp = df_view.nlargest(30, "涨跌幅")
            elif sort_by == "涨跌幅 ↑":
                df_disp = df_view.nsmallest(30, "涨跌幅")
            elif sort_by == "涨幅榜":
                df_disp = df_view[df_view["涨跌幅"] > 0].nlargest(30, "涨跌幅")
            elif sort_by == "跌幅榜":
                df_disp = df_view[df_view["涨跌幅"] < 0].nsmallest(30, "涨跌幅")
            elif sort_by == "成交额 ↓":
                df_disp = df_view.nlargest(30, "成交额(亿)")
            elif sort_by == "成交量 ↓":
                df_disp = df_view.nlargest(30, "成交量(万手)")
            elif sort_by == "主力净流入 ↓":
                df_disp = df_view.nlargest(30, "主力净流入(万)") if "主力净流入(万)" in df_view.columns else df_view
            elif sort_by == "换手率 ↓":
                df_disp = df_view.nlargest(30, "换手率%") if "换手率%" in df_view.columns else df_view

            cols_disp = [col_name, "最新价", "涨跌幅"]
            if "pe_ttm" in df_view.columns:
                cols_disp.append("pe_ttm")
            if "换手率%" in df_view.columns:
                cols_disp.append("换手率%")
            cols_disp.extend(["成交额(亿)", "成交量(万手)"])
            if "主力净流入(万)" in df_view.columns:
                cols_disp.append("主力净流入(万)")

            cols_disp = [c for c in cols_disp if c in df_disp.columns]

            st.dataframe(
                df_disp[cols_disp].head(30),
                use_container_width=True, hide_index=True,
            )

            # 涨幅榜/跌幅榜 Bar Chart
            fig = go.Figure()
            top_gain = df_view.nlargest(15, "涨跌幅")
            top_loss = df_view.nsmallest(15, "涨跌幅")
            combined = pd.concat([top_gain, top_loss])

            colors = ["#ef4444" if v > 0 else "#22c55e" for v in combined["涨跌幅"]]
            fig.add_trace(go.Bar(
                x=combined["涨跌幅"],
                y=combined[col_name],
                orientation="h",
                marker_color=colors,
                text=combined["涨跌幅"].round(2),
                textposition="outside",
            ))
            fig.update_layout(
                template="plotly_dark", height=500,
                title="涨幅榜 vs 跌幅榜 (Top 15)",
                xaxis_title="涨跌幅%",
                margin=dict(l=10, r=50, t=40, b=10),
                hovermode="y unified",
            )
            st.plotly_chart(fig, use_container_width=True)

        else:
            st.warning("快照获取失败，可能是非交易时段")

st.divider()
st.caption(f"📡 实时行情 · 数据来源: {'新浪/腾讯实时API' if in_session else 'PostgreSQL'} · {now_str}")