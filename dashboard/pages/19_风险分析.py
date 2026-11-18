"""风险分析 v2 — 蒙特卡洛/风险分解/极值理论/压力测试"""
import streamlit as st; import pandas as pd; import plotly.graph_objects as go
from datetime import datetime; import numpy as np
st.set_page_config(page_title="风险分析 v2", layout="wide")
from engine.api_adapter import get_stock_list
from engine.risk_analysis import (full_risk_report, get_stock_returns,
    get_benchmark_returns, compute_max_drawdown, factor_risk_decomposition,
    tail_risk_analysis, scenario_stress_test, portfolio_risk_report)
from engine.monte_carlo import simulate_gbm_paths, distribution_summary

st.markdown("""<style>
    .risk-card { background:#1a1a2e; border-radius:10px; padding:1.2rem; border:1px solid #2a2a3a; }
    .metric-green { color:#22c55e; font-size:1.8rem; font-weight:700; }
    .metric-red { color:#ef4444; font-size:1.8rem; font-weight:700; }
    .metric-yellow { color:#eab308; font-size:1.8rem; font-weight:700; }
    .label { color:#888; font-size:0.85rem; } .stApp { background-color:#0e1117; }
</style>""", unsafe_allow_html=True)

st.title("风险分析引擎 v2")
st.caption("VaR 回撤 蒙特卡洛(10K) Barra因子分解 极值理论 4情景压力测试")
stocks_df = get_stock_list()
labels = [f"{r['ts_code']} - {r['name']}" for _, r in stocks_df.iterrows()]
tab1,tab2,tab3,tab4 = st.tabs(["个股风险","蒙特卡洛","压力测试","组合风险"])

# ── Tab 1: 个股风险 ──
with tab1:
    col1,col2,col3,col4 = st.columns([2,1,1,1])
    with col1: sel = st.selectbox("选择股票", labels, index=0, key="r1")
    with col2: sd = st.text_input("起始","2025-01-01", key="r1s")
    with col3: ed = st.text_input("结束",datetime.now().strftime("%Y-%m-%d"), key="r1e")
    with col4: bc = st.text_input("基准","000300.SH", key="r1b")
    ts = sel.split(" -")[0]; nm = sel.split(" - ")[1]
    if st.button("生成风险报告", type="primary", use_container_width=True, key="br1"):
        sc=sd.replace("-",""); ec=ed.replace("-","")
        with st.spinner("计算指标..."):
            rpt = full_risk_report(ts, sc, ec, bc)
            dec = factor_risk_decomposition(ts, sc, ec)
            rets = get_stock_returns(ts, sc, ec)
            tail = tail_risk_analysis(rets["return"]) if not rets.empty else {}
        if "error" not in rpt:
            c=st.columns(5)
            c[0].metric("年化收益",f"{rpt.get('年化收益率','—')}%")
            c[1].metric("年化波动",f"{rpt.get('年化波动率','—')}%")
            c[2].metric("最大回撤",f"{rpt.get('max_drawdown_pct','—')}%")
            c[3].metric("Sharpe",rpt.get("Sharpe","—"))
            c[4].metric("Beta",rpt.get("beta","—"))
            if "error" not in dec:
                fig=go.Figure(data=[go.Pie(labels=["市场","行业","特质"],
                    values=[dec["market_risk_pct"],dec["industry_risk_pct"],dec["idiosyncratic_pct"]],
                    marker_colors=["#3b82f6","#eab308","#64748b"],textinfo="label+percent")])
                fig.update_layout(template="plotly_dark",height=300,title=f"风险分解 R²={dec.get('r_squared','—')}%")
                st.plotly_chart(fig, use_container_width=True)
            if "error" not in tail:
                st.markdown("### 尾部风险(EVT)")
                tc=st.columns(4)
                tc[0].metric("Tail VaR95%",f"{tail['tail_var_95_pct']}%")
                tc[1].metric("Tail VaR99%",f"{tail['tail_var_99_pct']}%")
                tc[2].metric("最大损失",f"{tail['max_single_loss_pct']}%")
                tc[3].metric("聚集天数",tail.get("avg_cluster_days","—"))
            [rpt.update({k:v}) for k,v in (dec if "error" not in dec else {}).items()]
            [rpt.update({k:v}) for k,v in (tail if "error" not in tail else {}).items()]

# ── Tab 2: 蒙特卡洛 ──
with tab2:
    c1,c2,c3 = st.columns([2,1,1])
    with c1: sm = st.selectbox("股票", labels, index=0, key="mcs")
    with c2: md = st.number_input("天数",60,756,252,30, key="mcd")
    with c3: ms = st.number_input("路径",1000,50000,10000,1000, key="mcsn")
    if st.button("运行蒙特卡洛", type="primary", use_container_width=True, key="bmc"):
        with st.spinner(f"模拟 {ms}路径×{md}天..."):
            sd=(datetime.now()-pd.DateOffset(years=2)).strftime("%Y%m%d")
            ed=datetime.now().strftime("%Y%m%d")
            rets=get_stock_returns(sm.split(" -")[0], sd, ed)
            if rets.empty: st.error("数据不足"); st.stop()
            paths,stats=simulate_gbm_paths(rets["return"],n_sim=ms,horizon_days=md)
        if paths is None:
            st.error(stats.get("error","失败"))
        else:
            c=st.columns(5)
            c[0].metric("终值中位数",stats["final_median"])
            c[1].metric("VaR 95%",f"{stats['var_95_pct']}%")
            c[2].metric("CVaR 95%",f"{stats['cvar_95_pct']}%")
            c[3].metric("亏损概率",f"{stats['loss_prob_pct']}%")
            c[4].metric("年化收益",f"{stats['annual_return_pct']:.1f}%")
            fig=go.Figure()
            for i in range(min(200,ms)):
                fig.add_trace(go.Scatter(y=paths[i],mode="lines",line=dict(width=0.5,color="rgba(59,130,246,0.2)"),showlegend=False,hoverinfo="skip"))
            med=np.median(paths,axis=0); p5=np.percentile(paths,5,axis=0); p95=np.percentile(paths,95,axis=0)
            fig.add_trace(go.Scatter(y=med,mode="lines",line=dict(color="#22c55e",width=3),name="中位数"))
            fig.add_trace(go.Scatter(y=p5,mode="lines",line=dict(color="#ef4444",width=2,dash="dash"),name="P5(VaR95%)"))
            fig.add_trace(go.Scatter(y=p95,mode="lines",line=dict(color="#3b82f6",width=2,dash="dash"),name="P95"))
            fig.add_hline(y=1,line_dash="dot",line_color="gray",opacity=0.3)
            fig.update_layout(template="plotly_dark",height=400,
                title=f"{sm.split(' - ')[1]} 蒙特卡洛 ({ms}路径)",hovermode="x unified")
            st.plotly_chart(fig,use_container_width=True)
            dist=distribution_summary(paths)
            if dist:
                st.dataframe(pd.DataFrame([{"分位":k,"净值":v} for k,v in dist.items()]),
                    hide_index=True,use_container_width=True)

# ── Tab 3: 压力测试 ──
with tab3:
    c1,c2 = st.columns([2,1])
    with c1: ss = st.selectbox("股票", labels, index=0, key="sts")
    with c2: ssd=st.text_input("起始","2025-01-01",key="sts_d")
    ts_s=ss.split(" -")[0]
    if st.button("运行压力测试",type="primary",use_container_width=True,key="bst"):
        with st.spinner("计算4情景..."):
            r=scenario_stress_test(ts_s, ssd.replace("-",""), datetime.now().strftime("%Y%m%d"))
        if "error" in r: st.error(r["error"])
        else:
            st.info(f"{r['stock_name']} · {r['industry']} · PE={r.get('current_pe','—')}")
            sc=r["scenarios"]; cols=st.columns(len(sc))
            for i,(k,info) in enumerate(sc.items()):
                with cols[i]:
                    im=info["impact_pct"]
                    cl="metric-red" if im<-5 else ("metric-yellow" if im<-2 else "metric-green")
                    st.markdown(f"""<div class="risk-card" style="text-align:center;">
                        <div class="label">{info['name']}</div>
                        <div class="{cl}">{im:+.2f}%</div>
                        <div style="color:#888;font-size:0.75rem;">{info['trigger'][:40]}</div></div>""",unsafe_allow_html=True)
            fig=go.Figure(data=[go.Bar(x=list(sc.keys()),y=[s["impact_pct"] for s in sc.values()],
                marker_color=["#ef4444" if i<-5 else "#eab308" for i in [s["impact_pct"] for s in sc.values()]],
                text=[f"{s['impact_pct']:+.1f}%" for s in sc.values()],textposition="outside")])
            fig.update_layout(template="plotly_dark",height=300,title="情景对比")
            st.plotly_chart(fig,use_container_width=True)

# ── Tab 4: 组合风险 ──
with tab4:
    st.markdown("### 组合风险 (多持仓加权)")
    nh=st.number_input("持仓数",1,10,3,key="pfn")
    holdings=[]
    for i in range(nh):
        c1,c2=st.columns([3,1])
        with c1: sh=st.selectbox(f"#{i+1}",labels,index=i%len(labels),key=f"pf_{i}",label_visibility="collapsed")
        with c2: w=st.number_input(f"w{i+1}",0.0,1.0,1.0/nh,step=0.05,key=f"pw_{i}",format="%.2f")
        holdings.append({"ts_code":sh.split(" -")[0],"weight":w})
    ws=sum(h["weight"] for h in holdings)
    if abs(ws-1)>0.01: st.warning(f"权重之和={ws:.2f},应为1")
    if st.button("组合风险",type="primary",use_container_width=True,key="bpf"):
        with st.spinner("计算组合风险..."):
            sd=(datetime.now()-pd.DateOffset(years=2)).strftime("%Y%m%d")
            ed=datetime.now().strftime("%Y%m%d")
            rpt=portfolio_risk_report(holdings,sd,ed)
        if "error" not in rpt:
            c=st.columns(4)
            c[0].metric("年化收益",f"{rpt.get('年化收益率','—')}%")
            c[1].metric("年化波动",f"{rpt.get('年化波动率','—')}%")
            c[2].metric("最大回撤",f"{rpt.get('max_drawdown_pct','—')}%")
            c[3].metric("Sharpe",rpt.get("Sharpe","—"))

st.caption(f"风险分析 v2 · Monte Carlo+Barra分解+EVT · {datetime.now():%Y-%m-%d %H:%M}")
