"""
📈 单票深度分析 — 日K/周K/月K + 可选技术指标 + 指标信号面板 + PDF导出
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px
import base64, io, os
from datetime import datetime, timedelta

st.set_page_config(page_title="单票分析", layout="wide")
st.title("📈 单票深度分析")

from engine.api_adapter import get_stock_list, query_single_stock, get_daily_basic, get_financial, get_moneyflow
from engine.query import query
from engine.api_adapter import get_stock_list, query_single_stock, get_daily_basic, get_financial, get_moneyflow
from engine.indicators import calc_all_indicators, calc_obv, calc_adx, calc_cci, calc_williams_r
from engine.indicators import eval_macd_signal, eval_rsi_signal, eval_kdj_signal
from engine.indicators import eval_boll_signal, eval_obv_signal, detect_macd_crosses
from engine.indicators import eval_adx_signal, eval_cci_signal, eval_wr_signal

# ===== 股票选择 & 参数 =====
stocks_df = get_stock_list()
stock_labels = [f"{r['ts_code']} - {r['name']}" for _, r in stocks_df.iterrows()]

col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
with col1:
    sel = st.selectbox("选择股票", stock_labels, index=0)
with col2:
    start = st.text_input("开始", "2025-01-01").replace("-", "")
with col3:
    end = st.text_input("结束", datetime.now().strftime("%Y-%m-%d")).replace("-", "")
with col4:
    freq = st.selectbox("周期", ["日线", "周K线", "月K线"], index=0)

ts_code = sel.split(" -")[0]
stock_name = sel.split(" - ", 1)[1]

# ===== 查询按钮 =====
col_btn, _ = st.columns([1, 5])
with col_btn:
    start_query = st.button("🔍 开始查询", type="primary", use_container_width=True)

if not start_query:
    st.info("👆 选择股票、日期范围和周期后，点击「开始查询」加载数据")
    st.stop()

# ===== 加载数据 =====
with st.spinner("加载数据..."):
    if freq == "日线":
        df = query_single_stock(ts_code, "ts_code,trade_date,open,high,low,close,vol,amount,pct_chg", start, end)
    else:
        freq_map = {"周K线": "weekly", "月K线": "monthly"}
        df = query(stocks=ts_code, fields="ts_code,trade_date,open,high,low,close,vol,amount",
                   start_date=start, end_date=end, freq=freq_map[freq])
        if not df.empty:
            df["pct_chg"] = df["close"].pct_change() * 100
    df_basic = get_daily_basic(ts_code, start, end)
    df_fi = get_financial(ts_code, start, end)
    df_mf = get_moneyflow(ts_code, start, end)
    df_bs = get_balancesheet(ts_code, start, end)
    df_cf = get_cashflow(ts_code, start, end)
    df_hd = get_top10_holders(ts_code, start, end)
    df_hn = get_stk_holdernumber(ts_code, start, end)

if df.empty:
    st.warning("无数据"); st.stop()

df = calc_all_indicators(df)
# 补充 OBV（calc_all_indicators 已包含）
df = calc_obv(df) if "OBV" not in df.columns else df
dates_axis = pd.to_datetime(df["trade_date"], format="%Y%m%d")

# ===== 合并基本面数据 =====
latest = df.iloc[-1]
if not df_basic.empty:
    lb = df_basic.iloc[-1]
    latest["pe_ttm"] = lb.get("pe_ttm")
    latest["pb"] = lb.get("pb")
    latest["turnover"] = lb.get("turnover_rate")

# ===== 指标卡 =====
m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("最新价", f"{latest['close']:.2f}", f"{latest.get('pct_chg', 0):+.2f}%")
m2.metric("PE-TTM", f"{latest['pe_ttm']:.2f}" if pd.notna(latest.get("pe_ttm")) else "N/A")
m3.metric("PB", f"{latest['pb']:.2f}" if pd.notna(latest.get("pb")) else "N/A")
m4.metric("成交量", f"{latest['vol']/10000:.0f}万" if pd.notna(latest.get("vol")) else "N/A")
m5.metric("成交额", f"{latest['amount']/1e5:.1f}亿" if pd.notna(latest.get("amount")) else "N/A")
m6.metric("换手率", f"{latest['turnover']:.2f}%" if pd.notna(latest.get("turnover")) else "N/A")

# ===== PDF 导出功能 =====
def build_pdf_report():
    from weasyprint import HTML
    closes = df["close"].values
    y_min, y_max = closes.min(), closes.max()
    y_range = max(y_max - y_min, 0.01)
    w, h_svg = 680, 260
    pad = 40
    n = max(len(closes) - 1, 1)
    def xp(i): return pad + (i / n) * (w - 2 * pad)
    def yp(v): return h_svg - pad - ((v - y_min) / y_range) * (h_svg - 2 * pad)
    poly = " ".join(f"{xp(i):.1f},{yp(v):.1f}" for i, v in enumerate(closes))
    area_fill = f"M{xp(0):.1f},{yp(closes[0]):.1f} {poly} L{xp(len(closes)-1):.1f},{h_svg-pad:.1f} L{xp(0):.1f},{h_svg-pad:.1f} Z"
    svg_chart = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h_svg}" style="display:block;margin:0 auto;">
      <rect width="{w}" height="{h_svg}" fill="#1a1a2e" rx="6"/>
      <path d="{area_fill}" fill="rgba(0,212,170,0.08)"/>
      <polyline points="{poly}" fill="none" stroke="#00d4aa" stroke-width="2" stroke-linejoin="round"/>
      <text x="{w/2}" y="{h_svg-8}" fill="#888" font-size="10" text-anchor="middle"
            font-family="'Noto Sans CJK SC','WenQuanYi Micro Hei',sans-serif">
        价格走势: {pd.to_datetime(df["trade_date"].iloc[0], format="%Y%m%d").strftime("%Y-%m-%d")}
        – {pd.to_datetime(df["trade_date"].iloc[-1], format="%Y%m%d").strftime("%Y-%m-%d")}
      </text>
    </svg>"""
    metrics_html = f"""<table>
      <tr><th>指标</th><th>值</th></tr>
      <tr><td>最新价</td><td>{latest['close']:.2f}</td></tr>
      <tr><td>涨跌幅</td><td style="color:{'#ef5350' if latest.get('pct_chg',0)>=0 else '#26a69a'}">{latest.get('pct_chg',0):+.2f}%</td></tr>
      <tr><td>PE-TTM</td><td>{f'{latest["pe_ttm"]:.2f}' if pd.notna(latest.get("pe_ttm")) else "N/A"}</td></tr>
      <tr><td>PB</td><td>{f'{latest["pb"]:.2f}' if pd.notna(latest.get("pb")) else "N/A"}</td></tr>
      <tr><td>成交量</td><td>{f'{latest["vol"]/10000:.0f}万' if pd.notna(latest.get("vol")) else "N/A"}</td></tr>
      <tr><td>成交额</td><td>{f'{latest["amount"]/1e5:.1f}亿' if pd.notna(latest.get("amount")) else "N/A"}</td></tr>
      <tr><td>换手率</td><td>{f'{latest["turnover"]:.2f}%' if pd.notna(latest.get("turnover")) else "N/A"}</td></tr>
      <tr><td>周期</td><td>{freq}</td></tr>
      <tr><td>数据区间</td><td>{df['trade_date'].iloc[0]} ~ {df['trade_date'].iloc[-1]} ({len(df)}条)</td></tr>
    </table>"""
    ind_labels = [
        ("MA5", "MA5"), ("MA10", "MA10"), ("MA20", "MA20"), ("MA60", "MA60"),
        ("MACD DIF", "MACD_DIF"), ("MACD DEA", "MACD_DEA"), ("MACD 柱", "MACD_HIST"),
        ("RSI(6)", "RSI6"), ("RSI(12)", "RSI12"), ("RSI(24)", "RSI24"),
        ("KDJ_K", "KDJ_K"), ("KDJ_D", "KDJ_D"), ("KDJ_J", "KDJ_J"),
        ("布林上轨", "BOLL_UP"), ("布林中轨", "BOLL_MID"), ("布林下轨", "BOLL_DN"),
    ]
    tech_rows = ""
    for label, col_name in ind_labels:
        if col_name in df.columns and pd.notna(latest.get(col_name)):
            tech_rows += f"<tr><td>{label}</td><td>{latest[col_name]:.2f}</td></tr>\n"
    tech_table = f"<table><tr><th>指标</th><th>最新值</th></tr>{tech_rows}</table>" if tech_rows else "<p>无技术指标</p>"
    fi_rows = ""
    if df_fi is not None and not df_fi.empty:
        fi_latest = df_fi.iloc[-1]
        for label, col in [("ROE(%)", "roe"), ("毛利率(%)", "gross_margin"),
                           ("净利率(%)", "net_margin"), ("营收(亿)", "revenue"),
                           ("净利润(亿)", "net_profit")]:
            if col in fi_latest.index and pd.notna(fi_latest.get(col)):
                v = fi_latest[col]
                v = v / 1e8 if col in ("revenue", "net_profit") else v
                fi_rows += f"<tr><td>{label}</td><td>{v:.2f}</td></tr>\n"
    fi_table = f"<table><tr><th>财务指标</th><th>最新值</th></tr>{fi_rows}</table>" if fi_rows else "<p>财务数据构建中</p>"
    css = """
      @page { size: A4; margin: 1.5cm 2cm; }
      body { font-family: 'Noto Sans CJK SC','WenQuanYi Micro Hei','DejaVu Sans',sans-serif;
             font-size: 10pt; line-height: 1.6; color: #e0e0e0; background: #0e1117; }
      h1 { font-size: 20pt; color: #00d4aa; text-align: center; border-bottom: 2px solid #00d4aa;
           padding-bottom: 8px; }
      h2 { font-size: 14pt; color: #42a5f5; border-bottom: 1px solid #333; padding-bottom: 4px;
           margin-top: 24px; }
      table { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 9.5pt; }
      th { background: #1a3a5c; color: #fff; padding: 6px 10px; text-align: left; }
      td { padding: 5px 10px; border-bottom: 1px solid #2a2a3a; }
      tr:nth-child(even) td { background: #141822; }
      .section { margin: 16px 0; }
      .footer { text-align: center; color: #666; font-size: 8pt; margin-top: 30px;
                border-top: 1px solid #333; padding-top: 10px; }
    """
    html = f"""<!DOCTYPE html><html lang="zh-CN">
    <head><meta charset="utf-8"><style>{css}</style></head>
    <body>
      <h1>{stock_name} ({ts_code}) — 综合报告</h1>
      <p style="text-align:center;color:#888;font-size:9pt;">生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
      <h2>📊 价格走势</h2>
      <div class="section">{svg_chart}</div>
      <h2>📋 关键指标</h2>
      <div class="section">{metrics_html}</div>
      <h2>📉 技术指标</h2>
      <div class="section">{tech_table}</div>
      <h2>📋 财务概要</h2>
      <div class="section">{fi_table}</div>
      <div class="footer">报告由 A股分析平台 生成 · 数据来源: Tushare Pro</div>
    </body></html>"""
    return HTML(string=html).write_pdf()

# ===== 选项卡（K线 → 指标信号 → 基本面 → 资金流 → 资产负债表 → 现金流量表 → 股东数据 → 数据）=====
tab_k, tab_sig, tab_fi, tab_mf, tab_bs, tab_cf, tab_hd, tab_data = st.tabs([
    "📊 K线", "📊 指标信号", "📋 基本面", "💰 资金流",
    "📜 资产负债表", "💵 现金流量表", "👥 股东数据", "📄 数据"
])

# ────────────────────────────────────────────
# Tab 0: K 线
# ────────────────────────────────────────────
with tab_k:
    st.subheader(f"{stock_name} ({ts_code}) — {freq}")
    ind_cols = st.columns(5)
    show_ma = ind_cols[0].checkbox("MA均线", value=True)
    show_macd = ind_cols[1].checkbox("MACD", value=True)
    show_rsi = ind_cols[2].checkbox("RSI", value=False)
    show_kdj = ind_cols[3].checkbox("KDJ", value=False)
    show_boll = ind_cols[4].checkbox("布林带", value=False)

    extra_rows = sum([show_macd, show_rsi, show_kdj])
    total_rows = 2 + extra_rows
    heights = [0.55] + [0.45 / max(total_rows - 1, 1)] * (total_rows - 1) if total_rows > 1 else [1]
    sub_titles = [f"{stock_name} ({ts_code})"]
    ind_map = {}
    current_row = 2
    if show_macd:
        sub_titles.append("MACD"); ind_map["MACD"] = current_row; current_row += 1
    if show_rsi:
        sub_titles.append("RSI (6/12/24)"); ind_map["RSI"] = current_row; current_row += 1
    if show_kdj:
        sub_titles.append("KDJ"); ind_map["KDJ"] = current_row; current_row += 1
    sub_titles.append("成交量")

    fig = make_subplots(rows=total_rows, cols=1, shared_xaxes=True,
                        vertical_spacing=0.06, row_heights=heights,
                        subplot_titles=sub_titles)

    # K线
    fig.add_trace(go.Candlestick(x=dates_axis, open=df["open"], high=df["high"],
                                 low=df["low"], close=df["close"], name="K线",
                                 increasing_line_color="#ef5350",
                                 decreasing_line_color="#26a69a"), row=1, col=1)
    # MA
    if show_ma:
        for ma, c in [("MA5", "#ffd740"), ("MA10", "#29b6f6"), ("MA20", "#ab47bc"), ("MA60", "#78909c")]:
            if ma in df.columns:
                fig.add_trace(go.Scatter(x=dates_axis, y=df[ma], mode="lines", name=ma,
                                         line=dict(color=c, width=1)), row=1, col=1)
    # 布林带
    if show_boll:
        for col, c, n in [("BOLL_UP", "#ef5350", "布林上轨"), ("BOLL_MID", "#ffd740", "布林中轨"),
                          ("BOLL_DN", "#26a69a", "布林下轨")]:
            if col in df.columns:
                fig.add_trace(go.Scatter(x=dates_axis, y=df[col], mode="lines",
                                         line=dict(color=c, width=0.8), name=n), row=1, col=1)

    # 成交量
    vol_row = total_rows
    vol_colors = ["#ef5350" if r["close"] >= r["open"] else "#26a69a" for _, r in df.iterrows()]
    fig.add_trace(go.Bar(x=dates_axis, y=df["vol"], marker_color=vol_colors,
                         opacity=0.7, name="成交量"), row=vol_row, col=1)

    # MACD
    if show_macd and "MACD_DIF" in df.columns:
        r = ind_map["MACD"]
        fig.add_trace(go.Scatter(x=dates_axis, y=df["MACD_DIF"], line=dict(color="#29b6f6"), name="DIF"), row=r, col=1)
        fig.add_trace(go.Scatter(x=dates_axis, y=df["MACD_DEA"], line=dict(color="#ffd740"), name="DEA"), row=r, col=1)
        bar_c = ["#ef5350" if v >= 0 else "#26a69a" for v in df["MACD_HIST"]]
        fig.add_trace(go.Bar(x=dates_axis, y=df["MACD_HIST"], marker_color=bar_c, name="柱"), row=r, col=1)

    # RSI
    if show_rsi and "RSI6" in df.columns:
        r = ind_map["RSI"]
        for rsi_col, c, l in [("RSI6", "#ff7043", "RSI6"), ("RSI12", "#42a5f5", "RSI12"), ("RSI24", "#66bb6a", "RSI24")]:
            fig.add_trace(go.Scatter(x=dates_axis, y=df[rsi_col], line=dict(color=c, width=1.5), name=l), row=r, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="#ef5350", opacity=0.5, row=r, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="#26a69a", opacity=0.5, row=r, col=1)

    # KDJ
    if show_kdj and "KDJ_K" in df.columns:
        r = ind_map["KDJ"]
        fig.add_trace(go.Scatter(x=dates_axis, y=df["KDJ_K"], line=dict(color="#29b6f6"), name="K"), row=r, col=1)
        fig.add_trace(go.Scatter(x=dates_axis, y=df["KDJ_D"], line=dict(color="#ffd740"), name="D"), row=r, col=1)
        fig.add_trace(go.Scatter(x=dates_axis, y=df["KDJ_J"], line=dict(color="#ab47bc"), name="J"), row=r, col=1)

    fig.update_layout(template="plotly_dark", height=200 + 160 * total_rows,
                      margin=dict(l=0, r=0, t=30, b=0),
                      xaxis_rangeslider_visible=False, hovermode="x unified",
                      legend=dict(orientation="h", y=1.02, x=0))
    st.plotly_chart(fig, use_container_width=True)

    if st.button("📄 导出PDF综合报告", type="primary"):
        with st.spinner("生成PDF中..."):
            pdf_bytes = build_pdf_report()
        st.download_button("📥 下载PDF报告", pdf_bytes,
                           f"{ts_code}_{freq}_{df['trade_date'].iloc[0]}_{df['trade_date'].iloc[-1]}.pdf",
                           "application/pdf")
        st.success(f"PDF 报告已生成 ({len(pdf_bytes)/1024:.0f}KB)")

# ────────────────────────────────────────────
# Tab 1: 指标信号
# ────────────────────────────────────────────
with tab_sig:
    st.subheader(f"🔍 {stock_name} ({ts_code}) — 常用指标信号总览")
    st.caption("基于选定周期数据计算的常用技术指标最新状态和信号判断")

    # 信号计算
    macd_sig = eval_macd_signal(df)
    rsi_sig = eval_rsi_signal(df)
    kdj_sig = eval_kdj_signal(df)
    boll_sig = eval_boll_signal(df)
    obv_sig = eval_obv_signal(df)
    crosses = detect_macd_crosses(df, lookback=180)

    # ── 信号面板 (5个指标卡片) ──
    col_a, col_b, col_c, col_d, col_e = st.columns(5)

    with col_a:
        st.markdown("**🔴 MACD**")
        if macd_sig:
            st.metric("DIF", f"{macd_sig['DIF']:.2f}")
            st.metric("DEA", f"{macd_sig['DEA']:.2f}")
            st.metric("柱", f"{macd_sig['HIST']:.2f}")
            st.caption(macd_sig["signal"])
        else:
            st.caption("数据不足")

    with col_b:
        st.markdown("**📈 RSI**")
        if rsi_sig:
            for col_name, (val, tag) in rsi_sig.items():
                st.metric(col_name, f"{val:.1f}", tag)
        else:
            st.caption("数据不足")

    with col_c:
        st.markdown("**📊 KDJ**")
        if kdj_sig:
            st.metric("K", f"{kdj_sig['K']:.1f}", kdj_sig.get("k_signal"))
            st.metric("D", f"{kdj_sig['D']:.1f}")
            st.metric("J", f"{kdj_sig['J']:.1f}")
            st.caption(kdj_sig.get("cross", ""))
        else:
            st.caption("数据不足")

    with col_d:
        st.markdown("**📦 布林带**")
        if boll_sig:
            st.metric("上轨", f"{boll_sig['UP']:.2f}")
            st.metric("中轨", f"{boll_sig['MID']:.2f}")
            st.metric("下轨", f"{boll_sig['DN']:.2f}")
            st.caption(f"位置: {boll_sig['position']:.0f}% — {boll_sig['zone']}")
        else:
            st.caption("数据不足")

    with col_e:
        st.markdown("**⚡ OBV 量能**")
        if obv_sig:
            st.metric("OBV", f"{obv_sig['OBV']:.0f}")
            st.metric("MA5", f"{obv_sig['MA5']:.0f}")
            st.caption(obv_sig.get("trend", ""))
            if obv_sig.get("divergence"):
                st.markdown(f"<p style='color:#ffd740;font-size:0.85rem;'>{obv_sig['divergence']}</p>",
                            unsafe_allow_html=True)
        else:
            st.caption("数据不足")

    st.markdown("---")
    st.caption("**高级指标** — 需 ≥30 个交易日")

    # 高级指标: ADX / CCI / WR%
    adx_sig = eval_adx_signal(df)
    cci_sig = eval_cci_signal(df)
    wr_sig = eval_wr_signal(df)

    col_f, col_g, col_h, _, _ = st.columns(5)
    with col_f:
        st.markdown("**📐 ADX 趋势强度**")
        if adx_sig:
            st.metric("ADX", f"{adx_sig['ADX']:.1f}")
            st.metric("+DI", f"{adx_sig['+DI']:.1f}" if pd.notna(adx_sig.get('+DI')) else "-")
            st.metric("-DI", f"{adx_sig['-DI']:.1f}" if pd.notna(adx_sig.get('-DI')) else "-")
            st.caption(f"{adx_sig['strength']} | {adx_sig['direction']}")
        else:
            st.caption("需要 ≥30 日数据")

    with col_g:
        st.markdown("**📊 CCI 顺势指标**")
        if cci_sig:
            st.metric("CCI", f"{cci_sig['CCI']:.1f}")
            st.caption(cci_sig.get("signal", ""))
        else:
            st.caption("需要 ≥30 日数据")

    with col_h:
        st.markdown("**📉 Williams %R**")
        if wr_sig:
            st.metric("WR", f"{wr_sig['WR']:.1f}")
            st.caption(wr_sig.get("signal", ""))
        else:
            st.caption("需要 ≥30 日数据")

    st.divider()

    # ── MACD 交叉信号表 ──
    col_x, col_y = st.columns(2)
    with col_x:
        st.markdown("**🔴 MACD 金叉记录** (最近10次)")
        if crosses.get("golden"):
            df_g = pd.DataFrame(crosses["golden"])
            df_g.columns = ["日期", "DIF", "DEA"]
            st.dataframe(df_g, use_container_width=True, hide_index=True)
        else:
            st.caption("无金叉记录")

    with col_y:
        st.markdown("**🟢 MACD 死叉记录** (最近10次)")
        if crosses.get("death"):
            df_d = pd.DataFrame(crosses["death"])
            df_d.columns = ["日期", "DIF", "DEA"]
            st.dataframe(df_d, use_container_width=True, hide_index=True)
        else:
            st.caption("无死叉记录")

    st.divider()

    # ── OBV + 价格双轴图 ──
    st.subheader("⚡ OBV 量能趋势")
    if "OBV" in df.columns:
        fig_obv = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                vertical_spacing=0.08,
                                row_heights=[0.5, 0.5],
                                subplot_titles=("价格走势", "OBV 量能指标"))
        fig_obv.add_trace(go.Scatter(x=dates_axis, y=df["close"], mode="lines",
                                     name="收盘价", line=dict(color="#00d4aa", width=1.5)),
                          row=1, col=1)
        fig_obv.add_trace(go.Scatter(x=dates_axis, y=df["OBV"], mode="lines",
                                     name="OBV", line=dict(color="#ef5350", width=1.5)),
                          row=2, col=1)
        if "OBV_MA5" in df.columns:
            fig_obv.add_trace(go.Scatter(x=dates_axis, y=df["OBV_MA5"], mode="lines",
                                         name="OBV_MA5", line=dict(color="#ffd740", width=1, dash="dot")),
                              row=2, col=1)
            fig_obv.add_trace(go.Scatter(x=dates_axis, y=df["OBV_MA10"], mode="lines",
                                         name="OBV_MA10", line=dict(color="#42a5f5", width=1, dash="dot")),
                              row=2, col=1)
        fig_obv.add_hline(y=0, line_dash="dot", line_color="gray", opacity=0.3, row=2, col=1)
        fig_obv.update_layout(template="plotly_dark", height=500, hovermode="x unified")
        st.plotly_chart(fig_obv, use_container_width=True)
    else:
        st.info("OBV 数据不足（需要 vol 成交量字段）")

# ────────────────────────────────────────────
# Tab 2: 基本面
# ────────────────────────────────────────────
with tab_fi:
    if df_fi is not None and not df_fi.empty and "roe" in df_fi.columns:
        fi_dates = pd.to_datetime(df_fi["end_date"])
        fig = go.Figure()
        if "roe" in df_fi.columns:
            fig.add_trace(go.Scatter(x=fi_dates, y=df_fi["roe"], mode="lines+markers",
                                     name="ROE", line=dict(color="#29b6f6")))
        if "gross_margin" in df_fi.columns:
            fig.add_trace(go.Scatter(x=fi_dates, y=df_fi["gross_margin"], mode="lines+markers",
                                     name="毛利率", line=dict(color="#66bb6a")))
        if "net_margin" in df_fi.columns:
            fig.add_trace(go.Scatter(x=fi_dates, y=df_fi["net_margin"], mode="lines+markers",
                                     name="净利率", line=dict(color="#42a5f5")))
        fig.update_layout(template="plotly_dark", height=400, title="财务指标趋势")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("财务数据构建中（后台自动补齐）")

# ────────────────────────────────────────────
# Tab 3: 资金流
# ────────────────────────────────────────────
with tab_mf:
    if df_mf is not None and not df_mf.empty and "net_mf_amount" in df_mf.columns:
        mf_dates = pd.to_datetime(df_mf["trade_date"], format="%Y%m%d")
        colors = ["#ef5350" if v > 0 else "#26a69a" for v in df_mf["net_mf_amount"]]
        fig = go.Figure()
        fig.add_trace(go.Bar(x=mf_dates, y=df_mf["net_mf_amount"], marker_color=colors, name="净流入"))
        fig.add_hline(y=0, line_color="white", opacity=0.3)
        fig.update_layout(template="plotly_dark", height=350, title="主力资金净流入")
        st.plotly_chart(fig, use_container_width=True)

        # 累计资金流曲线
        mf_cum = df_mf["net_mf_amount"].fillna(0).cumsum()
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=mf_dates, y=mf_cum, mode="lines", fill="tozeroy",
                                  name="累计净流入", line=dict(color="#ef5350", width=2)))
        fig2.update_layout(template="plotly_dark", height=250, title="累计资金净流入")
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("资金流数据构建中")

# ────────────────────────────────────────────
# Tab 4: 资产负债表
# ────────────────────────────────────────────
with tab_bs:
    if df_bs is not None and not df_bs.empty:
        bs_dates = pd.to_datetime(df_bs["end_date"])
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                            row_heights=[0.6, 0.4], vertical_spacing=0.08,
                            subplot_titles=("资产结构", "负债结构"))
        for col, c, n in [("total_assets", "#29b6f6", "总资产"),
                          ("total_hldr_eqy_exc_min_int", "#66bb6a", "净资产"),
                          ("total_liab", "#ef5350", "总负债")]:
            if col in df_bs.columns:
                fig.add_trace(go.Scatter(x=bs_dates, y=df_bs[col],
                                         mode="lines+markers", name=n,
                                         line=dict(color=c, width=2)), row=1, col=1)
        for col, c, n in [("st_borr", "#ffd740", "短期借款"),
                          ("lt_borr", "#ab47bc", "长期借款"),
                          ("acct_payable", "#ff7043", "应付账款")]:
            if col in df_bs.columns:
                fig.add_trace(go.Scatter(x=bs_dates, y=df_bs[col],
                                         mode="lines+markers", name=n,
                                         line=dict(color=c)), row=2, col=1)
        fig.update_layout(template="plotly_dark", height=500, hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)

        if "goodwill" in df_bs.columns and df_bs["goodwill"].sum() > 0:
            fig2 = go.Figure()
            fig2.add_trace(go.Bar(x=bs_dates, y=df_bs["goodwill"],
                                  marker_color="#ef5350", name="商誉"))
            fig2.update_layout(template="plotly_dark", height=250, title="商誉")
            st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("资产负债表数据已拉取")

# ────────────────────────────────────────────
# Tab 5: 现金流量表
# ────────────────────────────────────────────
with tab_cf:
    if df_cf is not None and not df_cf.empty:
        cf_dates = pd.to_datetime(df_cf["end_date"])
        fig = go.Figure()
        for col, c, n in [("n_cashflow_act", "#29b6f6", "经营现金流"),
                          ("n_cashflow_inv_act", "#ffd740", "投资现金流"),
                          ("n_cash_flows_fnc_act", "#ab47bc", "筹资现金流")]:
            if col in df_cf.columns:
                fig.add_trace(go.Scatter(x=cf_dates, y=df_cf[col],
                                         mode="lines+markers", name=n,
                                         line=dict(color=c, width=2)))
        fig.add_hline(y=0, line_dash="dot", line_color="gray", opacity=0.3)
        fig.update_layout(template="plotly_dark", height=400,
                          title="现金流趋势", hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)

        if "free_cashflow" in df_cf.columns:
            fig2 = go.Figure()
            colors2 = ["#26a69a" if v >= 0 else "#ef5350" for v in df_cf["free_cashflow"].fillna(0)]
            fig2.add_trace(go.Bar(x=cf_dates, y=df_cf["free_cashflow"],
                                  marker_color=colors2, name="自由现金流"))
            fig2.update_layout(template="plotly_dark", height=250, title="自由现金流")
            st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("现金流量表数据已拉取")

# ────────────────────────────────────────────
# Tab 6: 股东数据
# ────────────────────────────────────────────
with tab_hd:
    hd_col, hn_col = st.columns(2)
    with hd_col:
        st.subheader("🏛️ 前十大股东 (最新)")
        if df_hd is not None and not df_hd.empty:
            latest_hd = df_hd[df_hd["end_date"] == df_hd["end_date"].max()]
            if not latest_hd.empty:
                display = latest_hd[["holder_name", "hold_ratio", "hold_change"]].copy()
                display.columns = ["股东名称", "持股比例%", "变动"]
                st.dataframe(display, use_container_width=True, hide_index=True)
            with st.expander("查看全部历史"):
                st.dataframe(df_hd, use_container_width=True, height=300)
        else:
            st.info("无数据")
    with hn_col:
        st.subheader("👥 股东人数趋势")
        if df_hn is not None and not df_hn.empty:
            hn_dates = pd.to_datetime(df_hn["end_date"])
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=hn_dates, y=df_hn["holder_num"],
                                     mode="lines+markers", fill="tozeroy",
                                     name="股东人数", line=dict(color="#ffd740", width=2)))
            fig.update_layout(template="plotly_dark", height=300,
                              title="股东人数变化", hovermode="x unified")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("无数据")

# ────────────────────────────────────────────
# Tab 7: 数据
# ────────────────────────────────────────────
with tab_data:
    st.dataframe(df, use_container_width=True, height=600)
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📥 下载 CSV", csv, f"{ts_code}_{freq}_{start}_{end}.csv", "text/csv")