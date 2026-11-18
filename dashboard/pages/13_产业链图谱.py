"""
🏭 产业链图谱 — P2-④

对标: Wind 产业链中心 / Bloomberg SUPPLY
可视化: 上游→中游→下游 穿透 + 成分股清单
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from engine.industry_chain import get_all_chains, get_chain, get_chain_for_stock

st.set_page_config(page_title="产业链图谱", layout="wide")
st.title("🏭 产业链图谱")
st.caption("对标 Wind 产业链中心 / Bloomberg SUPPLY · 上游 → 中游 → 下游 全链路穿透")

chains = get_all_chains()

if not chains:
    st.error("产业链数据加载失败，请检查 engine/industry_chain.py")
    st.stop()

# ── 选择产业链 ──────────────────────────────────────
chain_options = {c["name"]: c["id"] for c in chains}
sel_chain = st.selectbox("选择产业链", list(chain_options.keys()), index=0)
chain = get_chain(chain_options[sel_chain])

st.subheader(f"📋 {chain['name']} 结构")
total_stocks = sum(len(s["stocks"]) for s in chain["stages"])
st.caption(f"{len(chain['stages'])} 个环节 · {total_stocks} 只成分股")

# ── 上下游穿透图 (Sankey) ────────────────────────────
colors_stage = ["#2196F3", "#4CAF50", "#FF9800", "#F44336", "#9C27B0"]

fig = go.Figure(data=[go.Sankey(
    node=dict(
        pad=20, thickness=20,
        label=[s["name"] for s in chain["stages"]],
        color=[colors_stage[i % len(colors_stage)] for i in range(len(chain["stages"]))],
        hovertemplate="%{label}<br>%{value} 只股票<extra></extra>"
    ),
    link=dict(
        source=[i for i in range(len(chain["stages"]) - 1)],
        target=[i + 1 for i in range(len(chain["stages"]) - 1)],
        value=[max(len(chain["stages"][i]["stocks"]), 1) for i in range(len(chain["stages"]) - 1)],
        color=["rgba(100,100,150,0.2)"] * (len(chain["stages"]) - 1),
    )
)])

fig.update_layout(
    title=f"{chain['name']} — 上下游穿透",
    height=200 + len(chain["stages"]) * 30,
    margin=dict(l=20, r=20, t=40, b=20),
    font=dict(size=14),
    template="plotly_dark",
)
st.plotly_chart(fig, use_container_width=True)

st.divider()

# ── 各环节成分股 ────────────────────────────────────
tabs_ = st.tabs([s["name"] for s in chain["stages"]])

for idx, (stage, tab) in enumerate(zip(chain["stages"], tabs_)):
    with tab:
        stocks = stage["stocks"]
        if not stocks:
            st.info("该环节暂无匹配的 A 股标的")
            continue

        df = pd.DataFrame(stocks)
        codes = df["ts_code"].tolist()

        if codes:
            from engine.query import sql
            try:
                quotes = sql(None,
                    "SELECT ts_code, close, pct_chg, amount FROM daily "
                    "WHERE ts_code = ANY(%s) "
                    "AND trade_date = (SELECT MAX(trade_date) FROM daily)",
                    params=[codes]
                )
                if not quotes.empty:
                    qmap = {
                        r["ts_code"]: (r["close"], r["pct_chg"], r["amount"])
                        for _, r in quotes.iterrows()
                    }
                    df["close"] = df["ts_code"].map(lambda x: qmap[x][0] if x in qmap else None)
                    df["pct_chg"] = df["ts_code"].map(lambda x: qmap[x][1] if x in qmap else None)
                    df["amount"] = df["ts_code"].map(lambda x: qmap[x][2] if x in qmap else None)
            except Exception as e:
                print(f"[chain] query error: {e}")

        if "amount" in df.columns:
            df = df.sort_values("amount", ascending=False, na_position="last")

        cols_show = [c for c in ["ts_code", "name", "industry", "market", "close", "pct_chg", "amount"] if c in df.columns]
        rename_map = {"ts_code": "代码", "name": "名称", "industry": "行业", "market": "板块",
                      "close": "收盘价", "pct_chg": "涨跌幅", "amount": "成交额"}
        df_display = df[cols_show].rename(columns=rename_map)

        if "涨跌幅" in df_display.columns:
            df_display["涨跌幅"] = df_display["涨跌幅"].apply(
                lambda x: f"{x:.2f}%" if pd.notna(x) else "-")
        if "成交额" in df_display.columns:
            df_display["成交额"] = df_display["成交额"].apply(
                lambda x: f"{x/1e8:.2f}亿" if pd.notna(x) else "-")

        st.dataframe(df_display, use_container_width=True, hide_index=True,
                     column_config={
                         "代码": st.column_config.TextColumn(width="small"),
                         "名称": st.column_config.TextColumn(width="medium"),
                         "行业": st.column_config.TextColumn(width="small"),
                     })
        st.caption(f"共 {len(df)} 只股票")

st.divider()

# ── 个股搜索 ────────────────────────────────────────
st.subheader("🔍 个股所属产业链查询")
search_code = st.text_input("输入股票代码（如 300750.SZ）", placeholder="300750.SZ", max_chars=16)

if search_code:
    with st.spinner("查询中..."):
        result = get_chain_for_stock(search_code)
        if result:
            st.success(f"**{search_code}** 所属产业链：")
            for info in result:
                st.markdown(f"- 🏭 **{info['chain_name']}** → 📍 **{info['stage']}**")
        else:
            st.warning(f"未找到 **{search_code}** 所属产业链，请检查代码或该股暂未被收录")

# ── 页脚 ────────────────────────────────────────────
st.divider()
col_stats = st.columns(len(chains))
for ci, c in enumerate(chains):
    ch = get_chain(c["id"])
    total = sum(len(s["stocks"]) for s in ch["stages"])
    col_stats[ci].metric(c["name"], f"{total} 只", f"{c['stages']} 环节")

st.caption(f"数据来源: Tushare Pro → PostgreSQL ashare · 产业链关系由小虎整理 · {len(chains)} 条产业链")