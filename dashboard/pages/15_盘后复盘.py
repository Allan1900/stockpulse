"""
P3-② 盘后复盘 — 每日收盘总览
对标: 券商晨会简报 / Bloomberg Brief
"""
import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="盘后复盘", layout="wide")
st.title("📋 盘后复盘")
st.caption("对标券商晨会简报 · 每日收盘后自动生成 · 交易日16:30飞书推送")

from engine.review import build_report, save_report

d = st.text_input("交易日", value=datetime.now().strftime("%Y%m%d"), max_chars=8)

if st.button("📄 生成复盘报告", type="primary", use_container_width=True):
    with st.spinner("采集数据·生成报告·推送飞书..."):
        text, data = build_report(d)
        path = save_report(d, text)
    st.markdown(text)
    st.caption(f"📁 已保存: {path}")
    from engine.review import push_feishu
    push_feishu(text)
else:
    st.info("👈 输入交易日并点击生成")

st.divider()
st.caption("P3-② · engine/review.py · 定时: 30 16 * * 1-5")
