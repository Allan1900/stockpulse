"""
📡 智能告警 — P2-③

规则引擎: 估值 / 资金异动 / 技术信号 / 成交量异动
推送: 飞书卡片（可配置开关）
"""
import os as _os
_DASH = _os.environ.get("SP_DASHBOARD_DIR") or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_DATA = _os.environ.get("SP_DATA_DIR") or _os.path.join(_os.path.expanduser("~"), "ashare_data")
import streamlit as st
import pandas as pd
import json, os
from datetime import datetime, date as dt_date

st.set_page_config(page_title="智能告警", layout="wide")
st.title("📡 智能告警")
st.caption("对标 Bloomberg ALRT · 估值阈值 / 资金异动 / 技术信号 / 成交量异动")

# ── 飞书推送配置 ──────────────────────────────────
FEISHU_CFG = _os.path.join(_DASH, "feishu_config.json")

def load_feishu_cfg():
    try:
        with open(FEISHU_CFG) as f:
            return json.load(f)
    except:
        return {"enabled": False, "webhook": ""}

def save_feishu_cfg(cfg):
    os.makedirs(os.path.dirname(FEISHU_CFG), exist_ok=True)
    with open(FEISHU_CFG, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

# ── 侧边栏控件 ──────────────────────────────────────
with st.sidebar:
    st.subheader("📡 告警设置")

    date = st.date_input("交易日", dt_date.today(), format="YYYY-MM-DD")
    date_str = date.strftime("%Y%m%d")

    # PE 阈值
    pe_high = st.slider("PE 高估阈值 (百分位)", 80, 99, 90, 1)
    pe_low = st.slider("PE 低估阈值 (百分位)", 1, 20, 10, 1)

    # 资金偏离
    zscore = st.slider("资金偏离标准差", 2.0, 5.0, 3.0, 0.5)

    # 成交量
    vol_ratio = st.slider("成交量倍数阈值", 2.0, 5.0, 3.0, 0.5)

    st.divider()

    # ── 飞书推送开关 ──────────────────────────────
    st.subheader("🔔 飞书推送")
    cfg = load_feishu_cfg()
    push_enabled = st.toggle("启用每日推送", value=cfg.get("enabled", False))
    wh = st.text_input("Webhook URL", value=cfg.get("webhook", ""),
                       placeholder="https://open.feishu.cn/...",
                       type="password")

    if push_enabled != cfg.get("enabled") or wh != cfg.get("webhook"):
        cfg["enabled"] = push_enabled
        cfg["webhook"] = wh
        save_feishu_cfg(cfg)
        if push_enabled and wh:
            st.success("✅ 推送已启用并保存")
        elif push_enabled and not wh:
            st.warning("⚠️ 已启用但未填写 Webhook URL")
        else:
            st.info("推送已关闭")

    do_run = st.button("🚀 运行告警引擎", type="primary", use_container_width=True)

# ── 主界面 ──────────────────────────────────────────

from engine.alerts import check_valuation, check_moneyflow, check_technical, check_volume

# 选择分析模式
tab_names = ["📊 估值告警", "💰 资金异动", "📈 技术信号", "🔥 成交量异动"]
tabs = st.tabs(tab_names)

if do_run or "alert_results" not in st.session_state:
    with st.spinner("运行告警引擎..."):
        v = check_valuation(date_str, pe_high, pe_low)
        m = check_moneyflow(date_str, zscore)
        t = check_technical(date_str)
        vol = check_volume(date_str, vol_ratio)
        st.session_state["alert_results"] = {
            "valuation": v, "moneyflow": m,
            "technical": t, "volume": vol,
            "date": date_str
        }
        # 如果启用了飞书推送，自动推送
        if push_enabled and wh:
            from engine.alerts import format_for_push, push_feishu
            msg = format_for_push(st.session_state["alert_results"], date_str)
            push_feishu(msg)

results = st.session_state.get("alert_results", {})
res_date = results.get("date", date_str)

# ── Tab 1: 估值告警 ────────────────────────────────
with tabs[0]:
    v_list = results.get("valuation", [])
    if v_list:
        df = pd.DataFrame(v_list)
        over = df[df["type"].str.contains("高估")].sort_values("value", ascending=False)
        under = df[df["type"].str.contains("低估")].sort_values("value")

        col_o, col_u = st.columns(2)
        with col_o:
            st.subheader(f"🔴 高估预警 ({len(over)} 条)")
            if not over.empty:
                st.dataframe(over[["name", "ts_code", "industry", "value", "threshold", "message"]],
                             use_container_width=True, hide_index=True)
            else:
                st.info("无高估预警")
        with col_u:
            st.subheader(f"🟢 低估预警 ({len(under)} 条)")
            if not under.empty:
                st.dataframe(under[["name", "ts_code", "industry", "value", "threshold", "message"]],
                             use_container_width=True, hide_index=True)
            else:
                st.info("无低估预警")
    else:
        st.info(f"⚠️ {res_date} 无可用的估值告警数据（需要 daily_basic 历史数据）")

# ── Tab 2: 资金异动 ────────────────────────────────
with tabs[1]:
    m_list = results.get("moneyflow", [])
    if m_list:
        df = pd.DataFrame(m_list)
        inflow = df[df["type"].str.contains("流入")].sort_values("value", ascending=False)
        outflow = df[df["type"].str.contains("流出")].sort_values("value", ascending=False)

        col_i, col_o = st.columns(2)
        with col_i:
            st.subheader(f"🟢 大幅流入 ({len(inflow)} 条)")
            if not inflow.empty:
                st.dataframe(inflow[["name", "ts_code", "industry", "value", "message"]],
                             use_container_width=True, hide_index=True)
            else:
                st.info("无大幅流入")
        with col_o:
            st.subheader(f"🔴 大幅流出 ({len(outflow)} 条)")
            if not outflow.empty:
                st.dataframe(outflow[["name", "ts_code", "industry", "value", "message"]],
                             use_container_width=True, hide_index=True)
            else:
                st.info("无大幅流出")
    else:
        st.info(f"⚠️ {res_date} 无可用的资金异动数据（需要 moneyflow 时序数据）")

# ── Tab 3: 技术信号 ────────────────────────────────
with tabs[2]:
    t_list = results.get("technical", [])
    if t_list:
        df = pd.DataFrame(t_list)
        gc = df[df["type"].str.contains("金叉")].sort_values("value", ascending=False)
        dc = df[df["type"].str.contains("死叉")].sort_values("value", ascending=True)

        col_g, col_d = st.columns(2)
        with col_g:
            st.subheader(f"🟢 金叉 ({len(gc)} 条)")
            if not gc.empty:
                st.dataframe(gc[["name", "ts_code", "industry", "value", "threshold", "message"]],
                             use_container_width=True, hide_index=True)
            else:
                st.info("无金叉信号")
        with col_d:
            st.subheader(f"🔴 死叉 ({len(dc)} 条)")
            if not dc.empty:
                st.dataframe(dc[["name", "ts_code", "industry", "value", "threshold", "message"]],
                             use_container_width=True, hide_index=True)
            else:
                st.info("无死叉信号")
    else:
        st.info(f"⚠️ {res_date} 无可用的技术信号（需要20日以上日线数据）")

# ── Tab 4: 成交量异动 ──────────────────────────────
with tabs[3]:
    vol_list = results.get("volume", [])
    if vol_list:
        df = pd.DataFrame(vol_list).sort_values("value", ascending=False)
        st.subheader(f"🔥 成交量异动 ({len(vol_list)} 条)")
        st.dataframe(df[["name", "ts_code", "industry", "value", "message"]],
                     use_container_width=True, hide_index=True)
    else:
        st.info(f"⚠️ {res_date} 无可用的成交量异动数据")

# ── 页脚 ────────────────────────────────────────────
st.divider()
col_status = st.columns(4)

total = sum(len(v) for v in results.values() if isinstance(v, list))
col_status[0].metric("总告警数", total)
col_status[1].metric("估值告警", len(results.get("valuation", [])))
col_status[2].metric("资金异动", len(results.get("moneyflow", [])))
col_status[3].metric("技术+成交量", len(results.get("technical", [])) + len(results.get("volume", [])))

st.caption(f"告警数据日期: {res_date} | 告警引擎运行于 Hermes Agent")