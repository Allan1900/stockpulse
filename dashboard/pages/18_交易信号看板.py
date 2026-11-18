"""P4-④ 交易信号看板 — 五位一体
因子 + 告警 + 盯盘 + Popper证伪(🔬) + Soros反身性(🔄)
"""
import os as _os
_DASH = _os.environ.get("SP_DASHBOARD_DIR") or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_DATA = _os.environ.get("SP_DATA_DIR") or _os.path.join(_os.path.expanduser("~"), "ashare_data")
import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="交易信号", layout="wide")
st.title("📊 P4-④ 自动交易信号")
st.caption("五位一体: 因子评分 + 四维告警 + 条件盯盘 + 🔬Popper证伪 + 🔄Soros反身性")

from engine.signals import consolidate, build_msg
from engine.falsify import falsification_summary
from engine.reflexivity import reflexivity_summary, STAGES

with st.sidebar:
    st.subheader("⚙️ 参数")
    date = st.text_input("交易日", value=datetime.now().strftime("%Y%m%d"), max_chars=8)
    only_bs = st.checkbox("仅BUY/SELL", value=True)
    show_watch = st.checkbox("显示WATCH", value=False)
    st.divider()
    st.caption("📖 Soros七阶段")
    for s in STAGES:
        st.caption(f"  {s['icon']} {s['name']:6s} → {s['signal']}")
    st.caption("⚠️ ≥2引擎共振才输出BUY/SELL")

if st.button("🚀 生成信号", type="primary", use_container_width=True):
    with st.spinner("因子评分→告警→盯盘→Popper证伪→Soros阶段识别..."):
        sig = consolidate(date)

    if sig.empty:
        st.warning("⚠️ 无信号（谨慎原则：默认HOLD）")
        st.stop()

    if only_bs:
        sig = sig[sig["signal"].isin(["BUY","SELL"])]
    if not show_watch:
        sig = sig[sig["signal"] != "WATCH"]
    if sig.empty:
        st.info("筛选后无信号")
        st.stop()

    for stype, icon in [("BUY","🟢"),("SELL","🔴"),("WATCH","🟡")]:
        sub = sig[sig["signal"]==stype]
        if sub.empty: continue
        st.subheader(f"{icon} {stype} ({len(sub)}只)")
        cols = [c for c in ["ts_code","name","confidence","falsify_score","reflex_name","reflex_icon","divergence_index","sources","detail"] if c in sub.columns]
        rename = {"ts_code":"代码","name":"名称","confidence":"置信度","falsify_score":"证伪分","reflex_name":"反身阶段","reflex_icon":"阶段","divergence_index":"发散指数","sources":"信号源","detail":"详情"}
        st.dataframe(sub[cols].rename(columns=rename), use_container_width=True, hide_index=True)
        st.divider()

    col1, col2, col3, col4, col5 = st.columns(5)
    cnt = sig["signal"].value_counts()
    col1.metric("🟢 BUY", int(cnt.get("BUY",0)))
    col2.metric("🔴 SELL", int(cnt.get("SELL",0)))
    col3.metric("🟡 WATCH", int(cnt.get("WATCH",0)))
    col4.metric("🔬 证伪通过率", f"{(sig['falsify_score']>-0.3).mean()*100:.0f}%")
    col5.metric("🔄 反身确认率", f"{(sig['reflex_signal']==sig['signal']).mean()*100:.0f}%")

    import os
    out_dir = _os.path.join(_DATA, "exports", "signals")
    os.makedirs(out_dir, exist_ok=True)
    sig.to_csv(f"{out_dir}/{date}.csv", index=False, encoding="utf-8-sig")
    st.caption(f"📁 已保存: {out_dir}/{date}.csv")

    with st.expander("📖 证伪+反身摘要"):
        r1, r2 = st.columns(2)
        with r1: st.info(falsification_summary(sig))
        with r2: st.info(reflexivity_summary(sig))

else:
    st.info("👈 选择日期并生成信号")
    st.markdown("""| 层 | 引擎 | 哲学 | 作用 |
|---|---|---|---|---|
| 📊 因子评分 | factors.py | 量化价值+质量+成长+动量 | 基础评分 |
| 🚨 四维告警 | alerts.py | 估值/资金/技术/量能 | 方向感知 |
| 👀 条件盯盘 | sentinel.py | 用户自定义规则 | 个性化过滤 |
| 🔬 证伪 | falsify.py 🆕 | **Popper证伪主义** | 主动寻找反驳证据 |
| 🔄 反身性 | reflexivity.py 🆕 | **Soros反身性** | 繁荣/衰退七阶段识别 |""")

st.divider()
st.caption("P4-④ · 五位一体 · 谨慎原则: ≥2引擎共振才输出方向信号 · 默认HOLD")