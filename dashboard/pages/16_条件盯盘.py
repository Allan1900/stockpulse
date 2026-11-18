import streamlit as st
import pandas as pd
import json, os
from datetime import datetime

st.set_page_config(page_title="条件盯盘", layout="wide")
st.title("👀 条件盯盘助手")
st.caption("对标 Wind 条件单 / 券商异动提醒 · 自定义盯盘条件 + 飞书实时推送")

from engine.sentinel import load_config, save_config, check_all, build_message, push_feishu
from engine.pg_query import query as pg_q

cfg = load_config()

with st.sidebar:
    st.subheader("⚙️ 推送设置")
    push_enabled = st.toggle("飞书推送", value=cfg.get("push_enabled", False), key="sentinel_push")
    if push_enabled != cfg.get("push_enabled"):
        cfg["push_enabled"] = push_enabled
        save_config(cfg)
    if push_enabled:
        wh = st.text_input("Webhook URL", value=cfg.get("webhook", ""), type="password", key="sentinel_wh")
        if wh != cfg.get("webhook"):
            cfg["webhook"] = wh
            save_config(cfg)
        st.caption("✅ 推送已启用")
    else:
        st.caption("⏸️ 推送已关闭")

    st.divider()
    refresh = st.number_input("刷新间隔(秒)", min_value=10, max_value=3600, value=cfg.get("refresh_interval", 60))
    if refresh != cfg.get("refresh_interval"):
        cfg["refresh_interval"] = refresh
        save_config(cfg)

# ── 条件列表 ────────────────────────────────────
st.subheader("📋 盯盘条件")

conds = cfg.get("conditions", [])
updated = False

for i, cond in enumerate(conds):
    cols = st.columns([3, 1, 1, 1, 1])
    with cols[0]:
        enabled = st.toggle(f"{cond['name']}", value=cond.get("enabled", False), key=f"cond_{i}")
        if enabled != cond.get("enabled"):
            cond["enabled"] = enabled
            updated = True
    with cols[1]:
        new_val = st.number_input("阈值", value=cond["value"], key=f"val_{i}")
        if new_val != cond["value"]:
            cond["value"] = new_val
            updated = True
    with cols[2]:
        new_op = st.selectbox("条件", ["gt", "lt"], index=0 if cond["operator"]=="gt" else 1,
                               format_func=lambda x: {">": "gt", "<": "lt"}[x],
                               key=f"op_{i}")
        if new_op != cond["operator"]:
            cond["operator"] = new_op
            updated = True
    with cols[3]:
        cond_type = cond["type"]
        type_label = {"valuation": "估值", "price": "股价", "moneyflow": "资金", "volume": "量能", "hsgt": "北向"}.get(cond_type, cond_type)
        st.caption(f"📊 {type_label}")
    with cols[4]:
        stocks_input = st.text_input("限定标的(逗号分隔)", value=",".join(cond.get("stocks", [])),
                                      key=f"stk_{i}")
        if stocks_input != ",".join(cond.get("stocks", [])):
            cond["stocks"] = [s.strip() for s in stocks_input.split(",") if s.strip()]
            updated = True

if updated:
    cfg["conditions"] = conds
    save_config(cfg)

st.divider()

# ── 运行检查 ────────────────────────────────────
date = st.text_input("交易日", value=datetime.now().strftime("%Y%m%d"), max_chars=8)

if st.button("🔍 执行盯盘检查", type="primary", use_container_width=True):
    with st.spinner("正在检查所有启用的盯盘条件..."):
        results = check_all(date)

    if not results:
        st.success("✅ 所有启用的盯盘条件均未触发")
    else:
        total = sum(r["count"] for r in results)
        st.warning(f"⚠️ {total} 条触发告警")

        for r in results:
            with st.expander(f"**{r['condition']}** — {r['count']} 条触发"):
                if r["alerts"]:
                    df = pd.DataFrame(r["alerts"])
                    cols_show = [c for c in ["ts_code", "name", "industry", "current", "message"] if c in df.columns]
                    rename = {"ts_code": "代码", "name": "名称", "industry": "行业", "current": "当前值", "message": "详情"}
                    st.dataframe(df[cols_show].rename(columns=rename), hide_index=True, use_container_width=True)

        # 推送
        msg = build_message(results, date)
        push_feishu(msg)
        if push_enabled:
            st.success("📤 已推送飞书")

    # 统计
    st.divider()
    col_s1, col_s2, col_s3, col_s4 = st.columns(4)
    enabled_count = sum(1 for c in conds if c.get("enabled"))
    col_s1.metric("启用条件", f"{enabled_count}/{len(conds)}")
    col_s2.metric("触发告警", sum(r["count"] for r in results) if results else 0)
    col_s3.metric("推送状态", "🟢 启用" if push_enabled else "🔴 关闭")
    col_s4.metric("刷新间隔", f"{refresh}s")

else:
    enabled_list = [c for c in conds if c.get("enabled")]
    if enabled_list:
        st.info(f"🔍 已启用 {len(enabled_list)} 条条件，点击上方按钮执行检查")
        for c in enabled_list:
            type_icon = {"valuation": "📊", "price": "📈", "moneyflow": "💰", "volume": "🔥", "hsgt": "🌐"}
            st.caption(f"  {type_icon.get(c['type'], '📌')} {c['name']} ({'>' if c['operator']=='gt' else '<'} {c['value']})")
    else:
        st.info("👈 先在左侧启用盯盘条件，然后点击执行检查")

st.divider()
st.caption("P3-③ · 引擎: engine/sentinel.py · 配置: sentinel_config.json · 支持飞书实时推送")