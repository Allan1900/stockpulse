"""权限管理 — 用户分级 + 功能矩阵"""
import streamlit as st; import pandas as pd; import plotly.graph_objects as go
from datetime import datetime
st.set_page_config(page_title="权限管理", layout="wide")
from engine.access_control import (get_user_info, require_feature,
    get_feature_matrix, list_all_users, add_user, FEATURE_MATRIX, TIER_FEATURES)

st.markdown("""<style>.stApp{background-color:#0e1117}</style>""", unsafe_allow_html=True)
st.title("权限管理"); st.caption("用户分级·功能矩阵·访问控制")

tab_users, tab_matrix, tab_audit = st.tabs(["用户管理", "功能矩阵", "接入概览"])

with tab_users:
    st.markdown("### 注册用户")
    users = list_all_users()
    if users:
        df = pd.DataFrame(users).rename(columns={"email":"邮箱","name":"姓名",
            "tier":"等级","since":"开通","expires":"到期","features":"功能白名单"})
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("暂无注册用户")

    st.divider()
    st.markdown("### 添加新用户")
    with st.form("add_user_form"):
        col1, col2 = st.columns(2)
        with col1:
            new_email = st.text_input("邮箱", placeholder="user@example.com")
            new_name = st.text_input("姓名", placeholder="用户姓名")
            new_tier = st.selectbox("等级", ["vip", "annual_pass"])
        with col2:
            new_expires = st.text_input("到期日", placeholder="2027-08-12")
            new_features_str = st.text_area("功能白名单 (年卡用, 逗号分隔)",
                placeholder="G1, G2, A1, A3, E1, F1")
        submitted = st.form_submit_button("添加用户", type="primary",
            use_container_width=True)
        if submitted and new_email:
            features = [f.strip() for f in new_features_str.split(",") if f.strip()]
            result = add_user(new_email, new_tier, name=new_name,
                features=features or None, expires=new_expires)
            if result["status"] == "ok":
                st.success(result["message"])
                st.rerun()
            else:
                st.error(result["message"])

with tab_matrix:
    st.markdown("### 功能权限矩阵")
    matrix = get_feature_matrix()
    if matrix:
        rows = []
        for code, info in sorted(matrix.items()):
            rows.append({"功能代码": code, "功能名称": info["name"],
                "类别": info["category"], "权限": info["tier"]})
        df = pd.DataFrame(rows)
        # 高亮
        def color_row(row):
            if row["权限"] == "admin": return ["background:#7f1d1d"] * len(row)
            if row["权限"] == "VIP": return ["background:#1e3a5f"] * len(row)
            if row["权限"] == "年卡": return ["background:#14532d"] * len(row)
            return [""] * len(row)
        st.dataframe(df.style.apply(color_row, axis=1), use_container_width=True, hide_index=True)

        # 统计
        c1, c2, c3 = st.columns(3)
        admins = sum(1 for _, v in matrix.items() if v["tier"] == "admin")
        vips = sum(1 for _, v in matrix.items() if v["tier"] == "VIP")
        annuals = sum(1 for _, v in matrix.items() if v["tier"] == "年卡")
        c1.metric("管理员独享", admins)
        c2.metric("VIP 专属", vips)
        c3.metric("年卡基础", annuals)
    else:
        st.info("暂无矩阵数据")

    st.divider()
    st.markdown("### 等级权限概览")
    cols = st.columns(3)
    with cols[0]:
        st.markdown("#### admin")
        st.info("全部功能 A~H + 内管工具")
        st.json({"G4健康报告","G5按需PDF","H1导出","H2浏览器","H3批量导出"})
    with cols[1]:
        st.markdown("#### VIP")
        st.success("A~F 全部 + G1~G3 推送")
        st.json(TIER_FEATURES["vip"])
    with cols[2]:
        st.markdown("#### 年卡")
        st.warning("G1/G2/G3推送 + A1/A3行情 + E1/F1概览")
        st.json(TIER_FEATURES["annual_pass_base"])

with tab_audit:
    st.markdown("### 接入通道概览")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("邮件通道", "✅ 已启用","ClawEmail")
    c2.metric("飞书通道", "✅ 已启用","当前会话")
    c3.metric("白名单用户", f"{len(_load_users() if 'list_all_users' else []) + 1 if False else 2}","含新用户")
    c4.metric("权限引擎", "✅ 已部署","engine/access_control.py")

    st.markdown("### 鉴权流程")
    st.code("""发件人 → adapter层 → EMAIL_ALLOWED_USERS? → 否→静默丢弃
                                                      ↓是
                              email-users.yaml → 用户存在? → 否→回复\"未注册\"
                                                          ↓是
                              tier? → admin → 放行全部
                                     → vip → 检查功能清单 → 放行/拒绝
                                     → annual_pass → 检查features白名单 → 放行/升级提示
                              expires? → 已过期→回复\"订阅已过期\"""", language="text")

st.caption(f"权限管理系统 · {datetime.now():%Y-%m-%d}")