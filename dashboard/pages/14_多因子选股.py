"""P3-① 多因子选股 Dashboard

对标 Wind 多因子模型 / Bloomberg GSFC
四维评分: 估值(30%) + 质量(25%) + 成长(25%) + 动量(20%)
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime

st.set_page_config(page_title="多因子选股", layout="wide")
st.title("📊 多因子选股模型")
st.caption("对标 Wind 多因子 / Bloomberg GSFC · 估值+质量+成长+动量 四维综合评分")

from engine.factors import compute_score, get_stock_basic
from engine.pg_query import query as pg_q

# ── 侧边栏参数 ──────────────────────────────────
with st.sidebar:
    st.subheader("🎛️ 选股参数")
    top_n = st.selectbox("展示数量", [10, 20, 30, 50, 100], index=1)
    sort_by = st.selectbox(
        "排序依据",
        ["total", "val_score", "qual_score", "gro_score", "mom_score"],
        format_func=lambda x: {"total": "综合分", "val_score": "估值",
                                "qual_score": "质量", "gro_score": "成长",
                                "mom_score": "动量"}[x],
    )

    industries = pg_q("SELECT DISTINCT industry FROM stock_basic WHERE industry IS NOT NULL ORDER BY industry")
    ind_opts = ["全部"] + industries["industry"].tolist()
    industry_filter = st.selectbox("行业筛选", ind_opts)

    st.divider()
    st.caption("因子权重: 估值30% · 质量25% · 成长25% · 动量20%")
    st.caption("数据日期: " + datetime.now().strftime("%Y%m%d"))

# ── 执行选股 ────────────────────────────────────
if st.button("🚀 运行选股引擎", type="primary", use_container_width=True):
    with st.spinner("正在计算四维因子评分..."):
        score = compute_score()

    if score.empty:
        st.error("评分失败，请检查数据库连接")
        st.stop()

    # 获取股票名称
    sb = get_stock_basic()
    name_map = dict(zip(sb["ts_code"], sb["name"]))
    ind_map = dict(zip(sb["ts_code"], sb["industry"]))

    score["name"] = score["ts_code"].map(name_map)
    score["industry"] = score["ts_code"].map(ind_map)

    # 行业过滤
    if industry_filter != "全部":
        score = score[score["industry"] == industry_filter]

    score = score.sort_values(sort_by, ascending=False).head(top_n)
    score["rank"] = range(1, len(score) + 1)

    # ── 排名表 ──────────────────────────────────
    display = score[["rank", "ts_code", "name", "industry", "total",
                      "val_score", "qual_score", "gro_score", "mom_score"]]
    rename = {"rank": "排名", "ts_code": "代码", "name": "名称", "industry": "行业",
              "total": "综合分", "val_score": "估值", "qual_score": "质量",
              "gro_score": "成长", "mom_score": "动量"}
    df_show = display.rename(columns=rename)

    for col in ["综合分", "估值", "质量", "成长", "动量"]:
        if col in df_show.columns:
            df_show[col] = df_show[col].round(1)

    st.subheader(f"🏆 选股排名 — 前{top_n}只")
    st.dataframe(df_show, use_container_width=True, hide_index=True,
                 column_config={
                     "排名": st.column_config.NumberColumn(width="small"),
                     "代码": st.column_config.TextColumn(width="small"),
                     "名称": st.column_config.TextColumn(width="medium"),
                     "行业": st.column_config.TextColumn(width="small"),
                     "综合分": st.column_config.NumberColumn(width="small", format="%.1f"),
                     "估值": st.column_config.NumberColumn(width="small", format="%.1f"),
                     "质量": st.column_config.NumberColumn(width="small", format="%.1f"),
                     "成长": st.column_config.NumberColumn(width="small", format="%.1f"),
                     "动量": st.column_config.NumberColumn(width="small", format="%.1f"),
                 })

    st.divider()

    # ── 雷达图：第一名 ──────────────────────────
    top1 = score.iloc[0]
    st.subheader(f"🥇 第一名详情 — {top1['name']} ({top1['ts_code'][:6]})")

    col_r1, col_r2 = st.columns([1, 1])
    with col_r1:
        fig = go.Figure()
        fig.add_trace(go.Scatterpolar(
            r=[top1["val_score"], top1["qual_score"], top1["gro_score"], top1["mom_score"]],
            theta=["估值", "质量", "成长", "动量"],
            fill="toself",
            line=dict(color="#00d4aa", width=2),
            marker=dict(size=8, color="#00d4aa"),
            name=top1["name"],
        ))
        fig.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
            height=350, margin=dict(l=40, r=40, t=20, b=20),
            template="plotly_dark", showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_r2:
        val_tag = "偏高✅" if top1["val_score"] > 60 else ("偏低⚠️" if top1["val_score"] < 40 else "适中")
        qual_tag = "优秀✅" if top1["qual_score"] > 60 else ("偏低⚠️" if top1["qual_score"] < 40 else "中等")
        gro_tag = "高增长✅" if top1["gro_score"] > 60 else ("低增长⚠️" if top1["gro_score"] < 40 else "稳健")
        mom_tag = "强势✅" if top1["mom_score"] > 60 else ("弱势⚠️" if top1["mom_score"] < 40 else "中性")

        st.markdown(f"""
| 维度 | 评分 | 行业均值 | 判断 |
|:----|:---:|:--------:|:----|
| 🏷️ 估值 | **{top1['val_score']:.0f}** | ~50 | {val_tag} |
| ⭐ 质量 | **{top1['qual_score']:.0f}** | ~50 | {qual_tag} |
| 📈 成长 | **{top1['gro_score']:.0f}** | ~50 | {gro_tag} |
| 🔄 动量 | **{top1['mom_score']:.0f}** | ~50 | {mom_tag} |
| **综合** | **{top1['total']:.1f}** | **~50** | |
        """)

    st.divider()

    # ── 行业分布 ──────────────────────────────────
    st.subheader("📊 行业分布")
    ind_dist = score["industry"].value_counts().head(10)
    fig2 = px.bar(
        x=ind_dist.values, y=ind_dist.index,
        orientation="h", color=ind_dist.values,
        color_continuous_scale="Viridis",
        labels={"x": "入选数量", "y": "行业"},
        height=350,
    )
    fig2.update_layout(template="plotly_dark", margin=dict(l=20, r=20, t=10, b=20))
    st.plotly_chart(fig2, use_container_width=True)

    # ── 概要指标 ──────────────────────────────────
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    col_m1.metric("覆盖股票", f"{len(score)}只", f"前{top_n}只")
    col_m2.metric("平均综合分", f"{score['total'].mean():.1f}", "行业均值50.0")
    col_m3.metric("最佳估值分", f"{score['val_score'].max():.0f}", f"{score[score['val_score']==score['val_score'].max()]['name'].iloc[0]}")
    col_m4.metric("最佳成长分", f"{score['gro_score'].max():.0f}", f"{score[score['gro_score']==score['gro_score'].max()]['name'].iloc[0]}")

else:
    st.info("👈 点击 **🚀 运行选股引擎** 开始综合评分")
    st.markdown("""
    ### 因子模型说明

    | 因子维度 | 权重 | 子指标 | 评分逻辑 |
    |:--------|:---:|:-------|:--------|
    | 📐 **估值** | 30% | PE_ttm / PB | 行业分位越低分越高（便宜优先） |
    | ⭐ **质量** | 25% | ROE / 毛利率 / 净利率 | 行业分位越高分越高 |
    | 📈 **成长** | 25% | 营收增速 / 利润增速 | 行业分位越高分越高 |
    | 🔄 **动量** | 20% | 近1月 / 近3月涨幅 | 行业分位越高分越高 |

    **数据:** daily_basic(PE/PB) + fina_indicator(ROE/增速) + daily(涨幅)
    **方法:** 行业中性化处理，消除行业偏差，同行业相对排名
    """)

st.divider()
st.caption("因子模型 v1.0 · 行业中性化 · 等权合成 · 数据来源: Tushare Pro → PostgreSQL · P3-①")