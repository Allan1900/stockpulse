"""ESG 评级 — 基于公开数据的简易 ESG 评分"""
import streamlit as st; import pandas as pd; import plotly.graph_objects as go
from datetime import datetime
st.set_page_config(page_title="ESG 评级", layout="wide")
from engine.esg import esg_score, esg_screen; from engine.query import get_stock_list

st.markdown("""<style>
    .esg-card { background:#1a1a2e; border-radius:10px; padding:1.2rem; border:1px solid #2a2a3a; text-align:center; }
    .score-AAA { color:#22c55e; font-size:2rem; font-weight:700; }
    .score-AA { color:#3b82f6; font-size:2rem; font-weight:700; }
    .score-A { color:#eab308; font-size:2rem; font-weight:700; }
    .score-BBB { color:#f97316; font-size:2rem; font-weight:700; }
    .score-B { color:#ef4444; font-size:2rem; font-weight:700; }
    .label { color:#888; font-size:0.85rem; }
    .stApp { background-color:#0e1117; }
</style>""", unsafe_allow_html=True)

st.title("ESG 评级"); st.caption("E 环境 · S 社会 · G 治理 — 基于公开财务数据")
tab1, tab2 = st.tabs(["个股评级", "全市场筛选"])

with tab1:
    stocks_df = get_stock_list()
    labels = [f"{r['ts_code']} - {r['name']}" for _, r in stocks_df.iterrows()]
    sel = st.selectbox("选择股票", labels, index=0, key="esg_sel")
    ts = sel.split(" -")[0]
    if st.button("计算 ESG", type="primary", use_container_width=True, key="btn_esg"):
        with st.spinner("计算 E/S/G 三维..."):
            r = esg_score(ts)
        cols = st.columns(4)
        grade = r["esg_grade"]; cls = "score-" + grade[:3]
        with cols[0]: st.markdown(f'<div class="esg-card"><div class="label">ESG 综合</div><div class="{cls}">{r["esg_score"]}</div><div class="label">{grade}</div></div>', unsafe_allow_html=True)
        with cols[1]: st.markdown(f'<div class="esg-card"><div class="label">E 环境</div><div class="score-AA" style="font-size:1.4rem">{r["e_score"]}</div><div class="label">{r["e_details"].get("env_category","")}</div></div>', unsafe_allow_html=True)
        with cols[2]: st.markdown(f'<div class="esg-card"><div class="label">S 社会</div><div class="score-A" style="font-size:1.4rem">{r["s_score"]}</div></div>', unsafe_allow_html=True)
        with cols[3]: st.markdown(f'<div class="esg-card"><div class="label">G 治理</div><div class="score-BBB" style="font-size:1.4rem">{r["g_score"]}</div></div>', unsafe_allow_html=True)
        fig = go.Figure(data=go.Scatterpolar(r=[r["e_score"],r["s_score"],r["g_score"],r["e_score"]],
            theta=["E 环境","S 社会","G 治理","E 环境"],fill="toself",name=r["name"]))
        fig.update_layout(template="plotly_dark",height=350,
            polar=dict(radialaxis=dict(visible=True,range=[0,100])),title=f'{r["name"]} ESG ({r["esg_grade"]})')
        st.plotly_chart(fig,use_container_width=True)
        st.json(r["e_details"]); st.json(r["s_details"]); st.json(r["g_details"])

with tab2:
    min_s = st.slider("最低分",0,100,30,key="esg_min")
    tn = st.number_input("数量",10,200,50,10,key="esg_top")
    if st.button("筛选",type="primary",use_container_width=True,key="btn_screen2"):
        with st.spinner("计算 ESG (限200只)..."):
            df = esg_screen(min_score=min_s, top_n=tn)
        if df.empty: st.warning("无结果")
        else:
            st.success(f"找到 {len(df)} 只")
            st.dataframe(df.sort_values("esg_score",ascending=False), use_container_width=True, hide_index=True)
            fig=go.Figure(data=[go.Histogram(x=df["esg_score"],nbinsx=20,marker_color="#3b82f6")])
            fig.update_layout(template="plotly_dark",height=300,title="ESG 分布")
            st.plotly_chart(fig,use_container_width=True)

st.caption(f"ESG 评级 · 基于公开财务数据 · {datetime.now():%Y-%m-%d}")
