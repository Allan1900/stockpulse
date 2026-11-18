"""StockPulse 研报系统 — 上传/存储/搜索/查看"""
import os as _os
_DASH = _os.environ.get("SP_DASHBOARD_DIR") or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_DATA = _os.environ.get("SP_DATA_DIR") or _os.path.join(_os.path.expanduser("~"), "ashare_data")
import streamlit as st
import pandas as pd
from datetime import datetime, date

st.set_page_config(page_title="研究报告", layout="wide")

from engine.research import (
    research_list,
    research_search,
    research_upload,
    research_get,
    research_delete,
)

# ── 样式 ─────────────────────────────────────────
st.markdown("""<style>
    .stApp { background-color:#0e1117; }
    .report-card {
        background:#1a1a2e; border-radius:10px; padding:1.2rem;
        border:1px solid #2a2a3a; margin:0.5rem 0;
    }
    .report-card h3 { margin:0 0 0.3rem 0; color:#f0f2f6; }
    .report-card .meta { color:#888; font-size:0.85rem; }
    .report-card .tags { margin:0.4rem 0; }
    .report-card .tag {
        display:inline-block; background:#1a3a5c; color:#42a5f5;
        padding:2px 10px; border-radius:12px; font-size:0.8rem; margin-right:6px;
    }
    .report-card .stock-badge {
        display:inline-block; background:#2d3748; color:#68d391;
        padding:2px 8px; border-radius:4px; font-size:0.75rem; margin-right:4px;
    }
    .report-card .preview { color:#aaa; font-size:0.9rem; line-height:1.5; margin-top:0.3rem; }
    .report-detail {
        background:#1a1a2e; border-radius:10px; padding:1.5rem;
        border:1px solid #2a2a3a;
    }
    .report-detail h2 { color:#f0f2f6; margin-top:0; }
    .report-detail .meta-line { color:#888; font-size:0.9rem; }
</style>""", unsafe_allow_html=True)

st.title("📄 研究报告")
st.caption("上传 / 搜索 / 查看 A 股研报")

# ── 会话状态 ─────────────────────────────────────
if "view_id" not in st.session_state:
    st.session_state.view_id = None

# ── Tabs ──────────────────────────────────────────
tab_list, tab_upload = st.tabs(["📋 研报列表", "📤 上传研报"])

# ══════════════════════════════════════════════════
# TAB 1: 研报列表
# ══════════════════════════════════════════════════
with tab_list:
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        search_q = st.text_input("🔍 搜索", placeholder="标题 / 标签 / 股票 / 内容...", key="search_input")
    with col2:
        sort_by = st.selectbox("排序", ["date", "title", "author"],
                               format_func=lambda x: {"date": "日期", "title": "标题", "author": "作者"}[x],
                               key="sort_select")
    with col3:
        if st.button("🔄 刷新", use_container_width=True):
            st.rerun()

    # 获取数据
    if search_q and search_q.strip():
        records = research_search(search_q)
    else:
        records = research_list(sort_by=sort_by)

    if not records:
        st.info("暂无研报，请先在「上传研报」页面上传。")
    else:
        st.success(f"共 {len(records)} 篇研报")

        for r in records:
            tags_html = "".join(f'<span class="tag">{t}</span>' for t in r.get("tags", []))
            stocks_html = "".join(f'<span class="stock-badge">{s}</span>' for s in r.get("stocks", []))
            preview = r.get("preview", "")[:200]

            st.markdown(f"""
            <div class="report-card">
                <h3>{r['title']}</h3>
                <div class="meta">
                    📅 {r.get('date', '')}  &nbsp;|&nbsp;  👤 {r.get('author', '未知')}
                    &nbsp;|&nbsp;  📎 {r.get('filename', '')}
                </div>
                <div class="tags">{tags_html}</div>
                <div>{stocks_html}</div>
                <div class="preview">{preview}{'…' if len(r.get('preview','')) > 200 else ''}</div>
            </div>
            """, unsafe_allow_html=True)

            col_a, col_b = st.columns([1, 5])
            with col_a:
                if st.button("📖 查看", key=f"view_{r['id']}", use_container_width=True):
                    st.session_state.view_id = r["id"]
                    st.rerun()
            with col_b:
                if st.button("🗑️ 删除", key=f"del_{r['id']}", use_container_width=True):
                    if research_delete(r["id"]):
                        st.success(f"已删除: {r['title']}")
                        st.rerun()
                    else:
                        st.error("删除失败")

# ══════════════════════════════════════════════════
# TAB 2: 上传研报
# ══════════════════════════════════════════════════
with tab_upload:
    st.subheader("📤 上传新研报")

    uploaded_file = st.file_uploader(
        "选择文件 (PDF / TXT / MD)",
        type=["pdf", "txt", "md"],
        key="file_uploader",
    )

    if uploaded_file is not None:
        col_a, col_b = st.columns(2)
        with col_a:
            title = st.text_input("标题 *", value=uploaded_file.name.rsplit(".", 1)[0],
                                  placeholder="研报标题", key="upload_title")
            author = st.text_input("作者 / 机构", placeholder="例如: 中信证券", key="upload_author")
        with col_b:
            date_val = st.date_input("日期", value=date.today(), key="upload_date")
            tags_str = st.text_input("标签 (逗号分隔)", placeholder="例如: 行业深度, 财报分析",
                                     key="upload_tags")
        stocks_str = st.text_input("关联股票 (逗号分隔)", placeholder="例如: 000001.SZ, 600519.SH",
                                   key="upload_stocks")

        if st.button("📤 上传", type="primary", use_container_width=True, key="btn_upload"):
            if not title.strip():
                st.error("请输入标题")
            elif uploaded_file.size == 0:
                st.error("文件为空")
            else:
                # 保存到临时文件
                tmp_dir = _os.path.join(_DASH, "tmp")
                os.makedirs(tmp_dir, exist_ok=True)
                tmp_path = os.path.join(tmp_dir, uploaded_file.name)
                with open(tmp_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())

                tags = [t.strip() for t in tags_str.split(",") if t.strip()]
                stocks = [s.strip() for s in stocks_str.split(",") if s.strip()]

                try:
                    record = research_upload(
                        file_path=tmp_path,
                        title=title.strip(),
                        author=author.strip() or "未知",
                        tags=tags,
                        stocks=stocks,
                    )
                    # 清理临时文件
                    os.remove(tmp_path)
                    st.success(f"✅ 上传成功: {record['title']}")
                    st.balloons()
                except Exception as e:
                    st.error(f"上传失败: {e}")

    st.markdown("---")
    st.caption("支持 PDF / TXT / Markdown 格式 · PDF 需安装 pypdf 或 pdfminer.six 以提取全文")

# ══════════════════════════════════════════════════
# 查看详情模态（通过 session_state 控制）
# ══════════════════════════════════════════════════
if st.session_state.view_id:
    r = research_get(st.session_state.view_id)
    if r:
        st.markdown("---")
        st.markdown('<div class="report-detail">', unsafe_allow_html=True)
        st.markdown(f"## {r['title']}")
        st.markdown(f"""
        <div class="meta-line">
            📅 {r.get('date', '')}  &nbsp;|&nbsp;  👤 {r.get('author', '未知')}
            &nbsp;|&nbsp;  📎 {r.get('filename', '')}
        </div>
        """, unsafe_allow_html=True)

        tags_html = "".join(f'<span class="tag">{t}</span>' for t in r.get("tags", []))
        stocks_html = "".join(f'<span class="stock-badge">{s}</span>' for s in r.get("stocks", []))
        st.markdown(f'<div style="margin:0.8rem 0;">{tags_html}{stocks_html}</div>',
                    unsafe_allow_html=True)

        content = r.get("content", "[无内容]")
        if content.startswith("[PDF") or content.startswith("[不支持") or content.startswith("[读取"):
            st.info(content)
        else:
            st.markdown("### 📝 全文")
            st.text_area("", value=content, height=500, label_visibility="collapsed")

        st.markdown("</div>", unsafe_allow_html=True)

        if st.button("⬅ 返回列表", use_container_width=True):
            st.session_state.view_id = None
            st.rerun()
    else:
        st.error("未找到该研报")
        if st.button("返回"):
            st.session_state.view_id = None
            st.rerun()

st.caption(f"StockPulse 研报系统 · {datetime.now():%Y-%m-%d %H:%M}")