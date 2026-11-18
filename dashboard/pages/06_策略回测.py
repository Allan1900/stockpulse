"""
🧪 策略回测引擎 v2 — 并行回测 + 参数扫描 + 多策略对比 + 绩效报告增强

升级内容:
  - 并行回测: 多股票同时运行
  - 参数扫描: Grid Search 参数优化
  - 多策略对比: 同时对比 4 种策略
  - 绩效报告增强: 整合风险指标 (Sharpe/Sortino/Calmar/回撤)
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

st.set_page_config(page_title="策略回测 v2", layout="wide")
st.title("🧪 策略回测引擎 v2")
st.caption("并行回测 · 参数扫描 · 多策略对比 · 风险绩效报告")

from engine.api_adapter import get_stock_list
from engine.backtest_engine import (
    STRATEGIES,
    backtest_single, parallel_backtest,
    param_grid_search, multi_strategy_comparison,
)

stocks_df = get_stock_list()
labels = [f"{r['ts_code']} - {r['name']}" for _, r in stocks_df.iterrows()]

# ===== 模式切换 =====
mode = st.radio("回测模式", ["📈 单股票单策略", "📊 多股票并行", "🔬 参数扫描优化", "⚖️ 多策略对比"],
                horizontal=True)

# ===== 公共参数 =====
col_period, col_com, col_slip = st.columns(3)
with col_period:
    start = st.text_input("回测起始", "2024-01-01").replace("-", "")
    end = st.text_input("回测结束", datetime.now().strftime("%Y-%m-%d"),
                        label_visibility="collapsed").replace("-", "")
with col_com:
    commission = st.number_input("佣金%", 0.01, 0.30, 0.03, step=0.01, format="%.2f")
with col_slip:
    slippage = st.number_input("滑点%", 0.01, 0.30, 0.05, step=0.01, format="%.2f")

# ════════════════════════════════════════════════════════════
# MODE 1: 单股票单策略
# ════════════════════════════════════════════════════════════
if mode == "📈 单股票单策略":
    col1, col2 = st.columns([2, 1])
    with col1:
        sel = st.selectbox("选择股票", labels, index=0, key="single_stock")
    with col2:
        strategy = st.selectbox("策略", list(STRATEGIES.keys()), index=0, key="single_strat")

    ts_code = sel.split(" -")[0]
    stock_name = sel.split(" - ")[1]

    # 策略参数
    st.markdown("**策略参数**")
    cols_p = st.columns(4)
    strategy_params = {}
    param_defs = STRATEGIES[strategy]["params"]
    for i, (pname, (pmin, pmax, pstep)) in enumerate(param_defs.items()):
        if "mul" in pname or "std" in pname:
            val = st.number_input(pname, float(pmin), float(pmax),
                                  float(pmin + (pmax - pmin) / 2), float(pstep),
                                  key=f"sp_{pname}", format="%.1f")
        else:
            val = st.number_input(pname, int(pmin), int(pmax),
                                  int(pmin + (pmax - pmin) / 2), int(pstep),
                                  key=f"sp_{pname}")
        strategy_params[pname] = val

    if st.button("▶ 运行回测", type="primary", use_container_width=True, key="btn_single"):
        with st.spinner(f"回测 {stock_name} ({ts_code}) — {strategy}…"):
            result = backtest_single(ts_code, start, end, strategy,
                                     strategy_params, commission, slippage)
        if not result:
            st.warning("无数据或回测失败"); st.stop()

        df = result["df"]
        trades = result["trades"]
        metrics = result["metrics"]
        eq_curve = result["equity_curve"]

        st.success(f"回测完成: {stock_name} | {strategy} ({start}~{end})")

        # ── 绩效指标卡 ──
        col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
        with col_m1:
            st.metric("总收益率", f"{metrics.get('总收益率%', 0):+.2f}%",
                      f"持有: {metrics.get('持有收益率%', 0):+.2f}%")
        with col_m2:
            st.metric("年化收益率", f"{metrics.get('年化收益率%', 0):+.2f}%")
        with col_m3:
            dd = metrics.get('最大回撤%', 0)
            st.metric("最大回撤", f"{dd:.2f}%",
                      delta=f"{metrics.get('最长回撤期(天)', 0)}天",
                      delta_color="inverse")
        with col_m4:
            st.metric("夏普比率", f"{metrics.get('夏普比率', 0):.2f}",
                      f"Sortino: {metrics.get('索提诺比率', 0):.2f}")
        with col_m5:
            st.metric("胜率", f"{metrics.get('胜率%', 0):.1f}%",
                      f"{metrics.get('交易次数', 0)}次交易")

        # ── 权益曲线 ──
        dates = pd.to_datetime(df["trade_date"], format="%Y%m%d")
        eq_df = eq_curve if len(eq_curve) == len(dates) else pd.Series([1.0])
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=dates, y=eq_df, mode="lines",
                                 name="策略净值", line=dict(color="#00d4aa", width=2)))
        buy_hold = df["close"] / df["close"].iloc[0]
        fig.add_trace(go.Scatter(x=dates, y=buy_hold, mode="lines",
                                 name="买入持有", line=dict(color="#78909c", width=1, dash="dot")))
        fig.add_hline(y=1, line_dash="dash", line_color="gray", opacity=0.3)
        fig.update_layout(template="plotly_dark", height=400, hovermode="x unified",
                          title="权益曲线", legend=dict(orientation="h", y=1.02))
        st.plotly_chart(fig, use_container_width=True)

        # ── 交易明细 ──
        if trades:
            st.subheader("📋 交易明细")
            df_trades = pd.DataFrame(trades)
            st.dataframe(df_trades, use_container_width=True, hide_index=True)
            csv = df_trades.to_csv(index=False).encode("utf-8-sig")
            st.download_button("📥 下载交易记录", csv,
                               f"回测_{ts_code}_{strategy}_{start}_{end}.csv", "text/csv")

            # 盈亏分布
            col_chart, _ = st.columns([1, 1])
            with col_chart:
                wins = len(df_trades[df_trades["收益率%"] > 0])
                losses = len(df_trades[df_trades["收益率%"] <= 0])
                if wins + losses > 0:
                    fig_pie = go.Figure(data=[go.Pie(
                        labels=["盈利", "亏损"], values=[wins, losses],
                        marker_colors=["#ef5350", "#26a69a"],
                        textinfo="label+percent")])
                    fig_pie.update_layout(template="plotly_dark", height=300, title="盈亏分布")
                    st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.info("该策略在回测期内未产生交易信号")

# ════════════════════════════════════════════════════════════
# MODE 2: 多股票并行回测
# ════════════════════════════════════════════════════════════
elif mode == "📊 多股票并行":
    col_s, col_n = st.columns([1, 1])
    with col_s:
        strategy = st.selectbox("策略", list(STRATEGIES.keys()), index=0, key="multi_strat")
    with col_n:
        num_stocks = st.number_input("股票数量", 2, 20, 5, key="num_multi")

    # 多股票选择
    stocks_selected = []
    cols_sel = st.columns(min(num_stocks, 5))
    for i in range(num_stocks):
        with cols_sel[i % 5]:
            s = st.selectbox(f"股票{i+1}", labels, index=i % len(labels),
                             key=f"ms_{i}")
            stocks_selected.append(s.split(" -")[0])

    # 策略参数
    st.markdown("**策略参数**")
    cols_p = st.columns(4)
    strategy_params = {}
    for i, (pname, (pmin, pmax, pstep)) in enumerate(STRATEGIES[strategy]["params"].items()):
        with cols_p[i % 4]:
            if "mul" in pname or "std" in pname:
                val = st.number_input(pname, float(pmin), float(pmax),
                                      float(pmin + (pmax - pmin) / 2), float(pstep),
                                      key=f"mp_{pname}", format="%.1f")
            else:
                val = st.number_input(pname, int(pmin), int(pmax),
                                      int(pmin + (pmax - pmin) / 2), int(pstep),
                                      key=f"mp_{pname}")
            strategy_params[pname] = val

    if st.button("▶ 并行回测", type="primary", use_container_width=True, key="btn_multi"):
        with st.spinner(f"并行回测 {len(stocks_selected)} 只股票…"):
            results = parallel_backtest(stocks_selected, start, end, strategy,
                                        strategy_params, commission, slippage,
                                        max_workers=min(len(stocks_selected), 8))
        if not results:
            st.warning("所有股票回测均失败"); st.stop()

        st.success(f"并行回测完成: {len(results)}/{len(stocks_selected)} 只股票有结果")

        # 横向对比表
        rows = []
        for r in results:
            m = r["metrics"]
            rows.append({
                "代码": r["code"], "总收益%": m.get("总收益率%", 0),
                "年化收益%": m.get("年化收益率%", 0),
                "夏普比率": m.get("夏普比率", 0),
                "索提诺比率": m.get("索提诺比率", 0),
                "最大回撤%": m.get("最大回撤%", 0),
                "胜率%": m.get("胜率%", 0),
                "交易次数": m.get("交易次数", 0),
            })
        df_compare = pd.DataFrame(rows).sort_values("夏普比率", ascending=False)
        st.subheader("📊 多股票对比")
        st.dataframe(df_compare, use_container_width=True, hide_index=True)

        # 合并权益曲线对比图
        fig = go.Figure()
        for r in results:
            eq = r["equity_curve"]
            dates_r = pd.to_datetime(r["df"]["trade_date"], format="%Y%m%d")
            eq_vals = eq if len(eq) == len(dates_r) else pd.Series([1.0])
            fig.add_trace(go.Scatter(x=dates_r, y=eq_vals, mode="lines",
                                     name=r["code"], line=dict(width=1.5)))
        fig.add_hline(y=1, line_dash="dash", line_color="gray", opacity=0.3)
        fig.update_layout(template="plotly_dark", height=450, hovermode="x unified",
                          title="多股票权益曲线对比",
                          legend=dict(orientation="h", y=1.02, font=dict(size=10)))
        st.plotly_chart(fig, use_container_width=True)

        # 热力图: 各股票绩效对比
        fig_heat = go.Figure(data=go.Heatmap(
            z=df_compare[["总收益%", "年化收益%", "夏普比率", "最大回撤%", "胜率%"]].values,
            x=["总收益%", "年化收益%", "夏普比率", "最大回撤%", "胜率%"],
            y=df_compare["代码"],
            colorscale="RdYlGn", zmid=0, texttemplate="%{z:.1f}",
        ))
        fig_heat.update_layout(template="plotly_dark", height=250 + 30 * len(df_compare),
                               title="多股票绩效热力图")
        st.plotly_chart(fig_heat, use_container_width=True)

        # CSV 导出
        csv_c = df_compare.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 下载对比数据", csv_c,
                           f"多股票回测_{strategy}_{start}_{end}.csv", "text/csv")

# ════════════════════════════════════════════════════════════
# MODE 3: 参数扫描优化
# ════════════════════════════════════════════════════════════
elif mode == "🔬 参数扫描优化":
    col_stock, col_strat = st.columns([2, 1])
    with col_stock:
        sel = st.selectbox("选择股票", labels, index=0, key="scan_stock")
    with col_strat:
        strategy = st.selectbox("策略", list(STRATEGIES.keys()), index=0, key="scan_strat")

    ts_code = sel.split(" -")[0]
    stock_name = sel.split(" - ")[1]

    # 参数范围设定
    st.markdown("**参数扫描范围**")
    scan_ranges = {}
    param_defs = STRATEGIES[strategy]["params"]
    cols_r = st.columns(len(param_defs))
    for i, (pname, (pmin, pmax, _)) in enumerate(param_defs.items()):
        with cols_r[i]:
            st.markdown(f"**{pname}**")
            lo = st.number_input(f"{pname}_最小", float(pmin), float(pmax),
                                 float(pmin), key=f"sr_lo_{pname}")
            hi = st.number_input(f"{pname}_最大", float(pmin), float(pmax),
                                 float(pmax), key=f"sr_hi_{pname}")
            step = st.number_input(f"{pname}_步长", 0.5, 10.0, 1.0, key=f"sr_st_{pname}")
            scan_ranges[pname] = np.arange(lo, hi + step / 2, step).tolist()

    if st.button("🔬 开始扫描", type="primary", use_container_width=True, key="btn_scan"):
        with st.spinner(f"参数扫描 {stock_name} — {strategy}…"):
            scan_result = param_grid_search(
                ts_code, start, end, strategy, scan_ranges,
                commission, slippage,
            )

        if scan_result["scan_results"].empty:
            st.warning("扫描无结果"); st.stop()

        st.success(f"参数扫描完成: 共 {scan_result['total_combs']} 种组合")
        st.info(f"**最优参数:** {scan_result['best_params']}  "
                f"| Sharpe: {scan_result['best_sharpe']:.3f}")

        # 最优参数运行结果
        if scan_result["best_metrics"]:
            m = scan_result["best_metrics"]
            cols = st.columns(5)
            with cols[0]: st.metric("总收益", f"{m.get('总收益率%', 0):+.2f}%")
            with cols[1]: st.metric("年化收益", f"{m.get('年化收益率%', 0):+.2f}%")
            with cols[2]: st.metric("最大回撤", f"{m.get('最大回撤%', 0):.2f}%")
            with cols[3]: st.metric("夏普比率", f"{m.get('夏普比率', 0):.2f}")
            with cols[4]: st.metric("胜率", f"{m.get('胜率%', 0):.1f}%")

        # 扫描结果表
        df_scan = scan_result["scan_results"]
        st.subheader("📊 参数扫描结果")
        st.dataframe(df_scan.sort_values("夏普比率", ascending=False),
                     use_container_width=True, hide_index=True)

        # 参数敏感性图 (如果只有1-2个参数可变)
        if len(scan_ranges) == 1:
            pname = list(scan_ranges.keys())[0]
            fig_s = go.Figure()
            fig_s.add_trace(go.Scatter(x=df_scan[pname], y=df_scan["夏普比率"],
                                        mode="lines+markers", name="Sharpe"))
            fig_s.update_layout(template="plotly_dark", height=350,
                                title=f"参数敏感性: {pname} vs Sharpe",
                                xaxis_title=pname, yaxis_title="夏普比率")
            st.plotly_chart(fig_s, use_container_width=True)

        elif len(scan_ranges) == 2:
            p1, p2 = list(scan_ranges.keys())[:2]
            fig_surf = go.Figure(data=go.Heatmap(
                x=df_scan[p1], y=df_scan[p2],
                z=df_scan["夏普比率"],
                colorscale="RdYlGn", zmid=0,
                texttemplate="%{z:.2f}",
            ))
            fig_surf.update_layout(template="plotly_dark", height=400,
                                    title=f"参数热力图: {p1} × {p2}",
                                    xaxis_title=p1, yaxis_title=p2)
            st.plotly_chart(fig_surf, use_container_width=True)

        csv_s = df_scan.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 下载扫描结果", csv_s,
                           f"参数扫描_{ts_code}_{strategy}_{start}_{end}.csv", "text/csv")

# ════════════════════════════════════════════════════════════
# MODE 4: 多策略对比
# ════════════════════════════════════════════════════════════
elif mode == "⚖️ 多策略对比":
    sel = st.selectbox("选择股票", labels, index=0, key="comp_stock")
    ts_code = sel.split(" -")[0]
    stock_name = sel.split(" - ")[1]

    if st.button("⚖️ 运行多策略对比", type="primary", use_container_width=True, key="btn_comp"):
        with st.spinner(f"运行 4 种策略对比…"):
            results = multi_strategy_comparison(ts_code, start, end, commission, slippage)
        if not results:
            st.warning("所有策略均失败"); st.stop()

        # 对比表
        rows = []
        for sname, res in results.items():
            m = res["metrics"]
            rows.append({
                "策略": sname,
                "总收益%": m.get("总收益率%", 0),
                "年化收益%": m.get("年化收益率%", 0),
                "夏普比率": m.get("夏普比率", 0),
                "索提诺比率": m.get("索提诺比率", 0),
                "最大回撤%": m.get("最大回撤%", 0),
                "回撤期(天)": m.get("最长回撤期(天)", 0),
                "胜率%": m.get("胜率%", 0),
                "交易次数": m.get("交易次数", 0),
            })
        df_comp = pd.DataFrame(rows).sort_values("夏普比率", ascending=False)
        st.subheader("📊 策略横向对比")
        st.dataframe(df_comp, use_container_width=True, hide_index=True)

        # 权益曲线叠加
        fig = go.Figure()
        for sname, res in results.items():
            eq = res["equity_curve"]
            dates_c = pd.to_datetime(res["df"]["trade_date"], format="%Y%m%d")
            eq_vals = eq if len(eq) == len(dates_c) else pd.Series([1.0])
            fig.add_trace(go.Scatter(x=dates_c, y=eq_vals, mode="lines",
                                     name=sname, line=dict(width=2)))
        # 买入持有
        df_base = list(results.values())[0]["df"]
        dates_c = pd.to_datetime(df_base["trade_date"], format="%Y%m%d")
        bh = df_base["close"] / df_base["close"].iloc[0]
        fig.add_trace(go.Scatter(x=dates_c, y=bh, mode="lines",
                                 name="买入持有", line=dict(color="#78909c", width=1, dash="dot")))
        fig.add_hline(y=1, line_dash="dash", line_color="gray", opacity=0.3)
        fig.update_layout(template="plotly_dark", height=450, hovermode="x unified",
                          title=f"{stock_name} — 多策略权益曲线对比",
                          legend=dict(orientation="h", y=1.02))
        st.plotly_chart(fig, use_container_width=True)

        # 绩效雷达图
        radar_categories = ["总收益%", "夏普比率", "索提诺比率", "胜率%", "交易次数"]
        radar_data = []
        for sname, res in results.items():
            m = res["metrics"]
            # 归一化 (0-100)
            radar_data.append(go.Scatterpolar(
                r=[
                    max(0, min(100, m.get("总收益率%", 0) + 50)),
                    max(0, min(100, (m.get("夏普比率", 0) + 2) * 20)),
                    max(0, min(100, (m.get("索提诺比率", 0) + 2) * 20)),
                    m.get("胜率%", 0),
                    min(100, m.get("交易次数", 0) * 5),
                ],
                theta=radar_categories,
                fill='toself', name=sname,
            ))
        fig_radar = go.Figure(data=radar_data)
        fig_radar.update_layout(template="plotly_dark", height=450,
                                polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                                title="策略绩效雷达图")
        st.plotly_chart(fig_radar, use_container_width=True)

        csv_comp = df_comp.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📥 下载策略对比", csv_comp,
                           f"多策略对比_{ts_code}_{start}_{end}.csv", "text/csv")

st.divider()
st.caption("🧪 策略回测引擎 v2 · 支持并行回测/参数扫描/多策略对比 · 数据来源: PostgreSQL")