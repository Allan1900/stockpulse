"""🔍 多票交叉对比 — 涨幅对比 / 指标矩阵 / 相关性 / 指标雷达"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime

st.set_page_config(page_title="多票对比", layout="wide")
st.title("🔍 多票交叉对比")

from engine.api_adapter import get_stock_list
from engine.query import query
from engine.indicators import calc_all_indicators, eval_macd_signal, eval_rsi_signal
from engine.indicators import eval_kdj_signal, eval_boll_signal, eval_obv_signal

stocks_df = get_stock_list()
labels = [f"{r['ts_code']} - {r['name']}" for _, r in stocks_df.iterrows()]

col1, col2, col3 = st.columns([3, 1, 1])
with col1:
    sel = st.multiselect("选择股票（2-6只）", labels, max_selections=6)
with col2:
    start = st.text_input("开始", "2025-01-01").replace("-", "")
with col3:
    end = st.text_input("结束", datetime.now().strftime("%Y-%m-%d")).replace("-", "")

if len(sel) < 2:
    st.info("请至少选择 2 只股票"); st.stop()

codes = [s.split(" -")[0] for s in sel]
names = [s.split(" - ")[1] for s in sel]

col_btn, _ = st.columns([1, 5])
with col_btn:
    start_query = st.button("🔍 开始对比", type="primary", use_container_width=True)

if not start_query:
    st.info("👆 选择股票和日期范围后，点击「开始对比」加载数据")
    st.stop()

with st.spinner("加载对比数据..."):
    df = query(stocks=codes, fields="ts_code,trade_date,close,open,high,low,vol,amount,pct_chg",
               start_date=start, end_date=end)

if df.empty:
    st.warning("无数据"); st.stop()

tab_comp, tab_indicators, tab_matrix, tab_corr, tab_raw = st.tabs([
    "📈 涨幅对比", "📊 指标对比", "📋 指标矩阵", "🔗 相关性", "📄 数据"
])

df["name"] = df["ts_code"].map(dict(zip(codes, names)))

# ────────────────────────────────────────────
# Tab 0: 涨幅对比
# ────────────────────────────────────────────
with tab_comp:
    fig = go.Figure()
    colors = px.colors.qualitative.Plotly
    for i, (code, name) in enumerate(zip(codes, names)):
        sub = df[df["ts_code"] == code].copy()
        if sub.empty: continue
        sub["pct"] = (sub["close"] / sub["close"].iloc[0] - 1) * 100
        d = pd.to_datetime(sub["trade_date"], format="%Y%m%d")
        fig.add_trace(go.Scatter(x=d, y=sub["pct"], mode="lines", name=name,
                                 line=dict(color=colors[i % len(colors)], width=2)))
    fig.add_hline(y=0, line_dash="dot", line_color="gray", opacity=0.5)
    fig.update_layout(template="plotly_dark", height=450, title="累计涨幅对比",
                      yaxis_title="涨幅 %", hovermode="x unified",
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig, use_container_width=True)

    rows_comp = []
    for code, name in zip(codes, names):
        sub = df[df["ts_code"] == code]
        if sub.empty: continue
        f, l = sub["close"].iloc[0], sub["close"].iloc[-1]
        rows_comp.append({"股票": name, "代码": code, "初始": f"{f:.2f}", "最新": f"{l:.2f}",
                          "涨幅": f"{(l/f-1)*100:+.2f}%",
                          "最高": f"{(sub['close'].max()/f-1)*100:+.2f}%",
                          "最低": f"{(sub['close'].min()/f-1)*100:+.2f}%"})
    st.dataframe(pd.DataFrame(rows_comp).sort_values("涨幅", ascending=False),
                 use_container_width=True, hide_index=True)

# ────────────────────────────────────────────
# Tab 1: 指标对比（雷达图 + 指标数值矩阵）
# ────────────────────────────────────────────
with tab_indicators:
    st.subheader("📊 常用指标对比")
    st.caption("各股票最新技术指标数值一览 — 用于快速比较多标的技术面强弱")

    # 对每只股票独立计算指标，取最新值
    indicator_data = []
    all_raw = {}
    for code, name in zip(codes, names):
        sub = df[df["ts_code"] == code].copy()
        if sub.empty: continue
        sub = calc_all_indicators(sub)
        sub = calc_obv(sub) if "OBV" not in sub.columns else sub

        macd_s = eval_macd_signal(sub)
        rsi_s = eval_rsi_signal(sub)
        kdj_s = eval_kdj_signal(sub)
        boll_s = eval_boll_signal(sub)
        obv_s = eval_obv_signal(sub)

        row = {
            "名称": name, "代码": code,
            "最新价": sub.iloc[-1]["close"],
            "涨幅%": sub.iloc[-1].get("pct_chg", 0),
        }

        # MACD
        if macd_s:
            row["MACD.DIF"] = macd_s.get("DIF")
            row["MACD.信号"] = macd_s.get("signal", "")
        # RSI
        if rsi_s and "RSI6" in rsi_s:
            row["RSI(6)"] = rsi_s["RSI6"][0]
        if rsi_s and "RSI12" in rsi_s:
            row["RSI(12)"] = rsi_s["RSI12"][0]
        # KDJ
        if kdj_s:
            row["KDJ.K"] = kdj_s.get("K")
            row["KDJ.交叉"] = kdj_s.get("cross", "")
        # 布林
        if boll_s:
            row["布林位置%"] = boll_s.get("position", "")
            row["布林区"] = boll_s.get("zone", "")
        # OBV
        if obv_s:
            trend_str = obv_s.get("trend", "")
            row["OBV趋势"] = trend_str
            row["OBV背离"] = obv_s.get("divergence", "")

        indicator_data.append(row)

        # 存原始数据用于雷达图
        raw = {"name": name, "code": code}
        if rsi_s and "RSI6" in rsi_s:
            raw["RSI"] = rsi_s["RSI6"][0]
        if rsi_s and "RSI12" in rsi_s:
            raw["RSI_S"] = rsi_s["RSI12"][0]
        if kdj_s:
            raw["KDJ_K"] = kdj_s.get("K", 50)
        if boll_s:
            raw["Boll%"] = boll_s.get("position", 50)
        all_raw[name] = raw

    # 指标数值表
    if indicator_data:
        df_ind = pd.DataFrame(indicator_data)
        st.dataframe(df_ind, use_container_width=True, hide_index=True)

        st.divider()

        # 雷达图 — 标准化维度
        radar_df = pd.DataFrame(all_raw).T.reset_index().rename(columns={"index": "name"})
        radar_dims = [c for c in radar_df.columns if c not in ("name", "code")]

        if len(radar_dims) >= 2 and len(radar_df) >= 2:
            st.subheader("📡 指标雷达对比")
            # 归一化到 0-100
            radar_norm = radar_df.copy()
            for dim in radar_dims:
                vals = radar_norm[dim]
                vmin, vmax = vals.min(), vals.max()
                radar_norm[dim] = (vals - vmin) / (vmax - vmin + 1e-10) * 100

            fig_radar = go.Figure()
            for _, r in radar_norm.iterrows():
                vals = [r[dim] for dim in radar_dims] + [r[radar_dims[0]]]
                fig_radar.add_trace(go.Scatterpolar(
                    r=vals,
                    theta=radar_dims + [radar_dims[0]],
                    fill="toself",
                    name=r["name"],
                    line=dict(width=2),
                ))
            fig_radar.update_layout(
                template="plotly_dark",
                polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                height=500,
                title="指标雷达对比（归一化 0-100）",
            )
            st.plotly_chart(fig_radar, use_container_width=True)

    # 涨跌幅排行柱状图
    st.divider()
    st.subheader("🏆 区间涨跌幅排行")
    perf_rows = []
    for code, name in zip(codes, names):
        sub = df[df["ts_code"] == code]
        if sub.empty: continue
        ret = (sub["close"].iloc[-1] / sub["close"].iloc[0] - 1) * 100
        perf_rows.append({"name": name, "return": ret})
    perf_df = pd.DataFrame(perf_rows).sort_values("return")
    colors_perf = ["#ef5350" if v >= 0 else "#26a69a" for v in perf_df["return"]]
    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(y=perf_df["name"], x=perf_df["return"], orientation="h",
                             marker_color=colors_perf,
                             text=[f"{v:+.2f}%" for v in perf_df["return"]],
                             textposition="outside"))
    fig_bar.add_vline(x=0, line_dash="dot", line_color="gray", opacity=0.5)
    fig_bar.update_layout(template="plotly_dark", height=400,
                          xaxis_title="区间涨幅 %", margin=dict(l=0, r=0, t=0, b=0))
    st.plotly_chart(fig_bar, use_container_width=True)

# ────────────────────────────────────────────
# Tab 2: 指标矩阵（指标对比表）
# ────────────────────────────────────────────
with tab_matrix:
    rows_mat = []
    for code, name in zip(codes, names):
        sub = df[df["ts_code"] == code]
        if sub.empty: continue
        last = sub.iloc[-1]
        rows_mat.append({"股票": name,
                         "最新价": f"{last['close']:.2f}",
                         "日均成交额(亿)": f"{sub['amount'].mean()/1e5:.2f}",
                         "波动率": f"{sub['pct_chg'].std():.2f}%",
                         "日均换手": f"{sub['vol'].mean()/1e4:.0f}万手"})
    st.dataframe(pd.DataFrame(rows_mat), use_container_width=True, hide_index=True)

# ────────────────────────────────────────────
# Tab 3: 相关性矩阵
# ────────────────────────────────────────────
with tab_corr:
    rets = {}
    for code, name in zip(codes, names):
        sub = df[df["ts_code"] == code].copy()
        if sub.empty: continue
        sub["ret"] = sub["pct_chg"] / 100
        rets[name] = sub.set_index("trade_date")["ret"]
    ret_df = pd.DataFrame(rets)
    if not ret_df.empty and ret_df.shape[1] >= 2:
        fig = px.imshow(ret_df.corr(), text_auto=".3f", aspect="auto",
                        color_continuous_scale=["#26a69a", "#263238", "#ef5350"],
                        title="收益率相关系数")
        fig.update_layout(template="plotly_dark", height=450)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("数据不足")

# ────────────────────────────────────────────
# Tab 4: 数据
# ────────────────────────────────────────────
with tab_raw:
    st.dataframe(df, use_container_width=True, height=500)
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📥 下载 CSV", csv, f"对比_{start}_{end}.csv", "text/csv")