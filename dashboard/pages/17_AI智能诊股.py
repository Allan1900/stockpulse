"""
P4-① AI智能诊股 — 全景诊断看板
整合因子评分+财务+资金+技术+产业链，输出个股全景诊断报告
"""
import os as _os
_DASH = _os.environ.get("SP_DASHBOARD_DIR") or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_DATA = _os.environ.get("SP_DATA_DIR") or _os.path.join(_os.path.expanduser("~"), "ashare_data")
import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="AI智能诊股", layout="wide")
st.title("🧠 AI 智能诊股")
st.caption("对标券商个股深度研报 · 因子评分+财务+资金+技术+产业链 全景诊断")

from engine.diagnostics import diagnose_stock

col_inp, col_date = st.columns([4, 1])
with col_inp:
    ts_code = st.text_input("股票代码", value="300750.SZ", max_chars=16,
                            placeholder="如 300750.SZ, 600519.SH, 000858.SZ")
with col_date:
    date = st.text_input("交易日", value=datetime.now().strftime("%Y%m%d"), max_chars=8)

if st.button("🧠 生成诊断报告", type="primary", use_container_width=True):
    with st.spinner(f"正在采集 {ts_code} 全维度数据..."):
        report = diagnose_stock(ts_code, date)
    st.markdown(report)
    out_dir = _os.path.join(_DATA, "exports", "diagnostics")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{ts_code[:6]}_{date}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    st.caption(f"📁 已保存: {out_path}")
else:
    st.info("👈 输入股票代码，点击生成诊断报告")
    st.divider()
    st.subheader("⚡ 快速诊股")
    quick = [("300750.SZ","宁德时代","锂电"),("600519.SH","贵州茅台","白酒"),
             ("000858.SZ","五粮液","白酒"),("300059.SZ","东方财富","金融"),
             ("688981.SH","中芯国际","半导体"),("002594.SZ","比亚迪","汽车")]
    cols = st.columns(6)
    for ci, (code, name, ind) in enumerate(quick):
        with cols[ci]:
            if st.button(f"{name}\n{code[:6]}", use_container_width=True):
                st.switch_page(f"pages/17_AI智能诊股.py?ts_code={code}")

st.divider()
st.caption("P4-① · engine/diagnostics.py · 数据: Tushare Pro -> PostgreSQL")
