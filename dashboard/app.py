"""A 股交叉分析平台 — 使用说明"""
import os as _os
_DASH = _os.environ.get("SP_DASHBOARD_DIR") or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_DATA = _os.environ.get("SP_DATA_DIR") or _os.path.join(_os.path.expanduser("~"), "ashare_data")
import streamlit as st

st.set_page_config(page_title="A 股交叉分析平台", page_icon="📊", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown("""
<style>
    .main > div { padding: 1rem 1.5rem; }
    .stApp { background-color: #0e1117; }
    h1, h2, h3 { color: #f0f2f6; }
    .card { background: #1a1a2e; border-radius: 10px; padding: 1.5rem; margin: 1rem 0;
            border: 1px solid #2a2a3a; }
    .card h3 { margin-top: 0; }
    .card p { color: #aaa; line-height: 1.7; }
    .tag { display: inline-block; background: #1a3a5c; color: #42a5f5; padding: 2px 10px;
           border-radius: 12px; font-size: 0.8rem; margin-right: 6px; }

    /* ════════════════════════════════════════════════
       移动端适配 — Mobile Responsive
       ════════════════════════════════════════════════ */
    @media (max-width: 768px) {
        .main > div { padding: 0.5rem 0.8rem; }
        h1 { font-size: 1.4rem !important; }
        h2 { font-size: 1.2rem !important; }
        h3 { font-size: 1.0rem !important; }
        .card { padding: 1rem; margin: 0.5rem 0; }
        /* 导航网格调整 */
        .stHorizontal > div { gap: 0.25rem !important; }
        .stHorizontal a { font-size: 0.75rem !important; padding: 0.2rem 0.4rem !important; }
        /* 表格字体适配 */
        .stDataFrame { font-size: 0.75rem !important; }
        /* 指标卡适配 */
        [data-testid="metric-container"] { padding: 0.3rem !important; }
        [data-testid="metric-container"] label { font-size: 0.7rem !important; }
        [data-testid="metric-container"] [data-testid="metric-value"] { font-size: 1.1rem !important; }
        /* 按钮全宽 */
        .stButton button { width: 100% !important; font-size: 0.85rem !important; }
        /* 输入框紧凑 */
        .stTextInput input, .stNumberInput input { font-size: 0.85rem !important; }
        /* Tabs */
        .stTabs [data-baseweb="tab"] { font-size: 0.75rem !important; padding: 4px 10px !important; }
        /* 隐藏侧边栏或折叠 */
        .stSidebar { width: 100% !important; }
        /* 图表演示 */
        .stPlotlyChart { height: auto !important; }
        /* selectbox */
        .stSelectbox div { font-size: 0.8rem !important; }
    }
    @media (max-width: 480px) {
        h1 { font-size: 1.2rem !important; }
        .tag { font-size: 0.65rem !important; padding: 1px 6px !important; }
        /* 小屏隐藏部分非关键列 */
        .stHorizontal > div:nth-child(n+7) { display: none; }
    }
</style>
""", unsafe_allow_html=True)

from engine.api_adapter import get_backend, get_backend_label, get_pg_stats

with st.sidebar:
    st.title("📊 A 股交叉分析平台")
    backend = get_backend()
    label = get_backend_label()
    st.caption(f"后端: {label}")
    st.divider()

    st.subheader("🗄 数据状态")
    if backend == "postgresql":
        stats = get_pg_stats()
        if stats:
            st.success(f"🐘 PostgreSQL ({stats['version']})")
            st.text(f"📦 总大小: {stats['db_size']}")
            st.markdown("**TOP 表行数:")
            for r in stats["rows"]:
                st.text(f"  {r['table']:20s} {r['rows']:>9,} 行  {r['size']}")
    else:
        st.info("SQLite 后端 — 部分功能受限")

    st.divider()
    st.subheader("🔔 推送设置")
    import json, os
    _cfg_path = _os.path.join(_DASH, "feishu_config.json")
    try:
        with open(_cfg_path) as _f:
            _fc = json.load(_f)
    except:
        _fc = {"enabled": False, "webhook": ""}
    _push = st.toggle("飞书推送", value=_fc.get("enabled", False), key="feishu_toggle")
    if _push != _fc.get("enabled", False):
        _fc["enabled"] = _push
        with open(_cfg_path, "w") as _f:
            json.dump(_fc, _f, indent=2, ensure_ascii=False)
    if _push:
        _wh = st.text_input("Webhook URL", value=_fc.get("webhook", ""),
                            type="password", key="feishu_wh",
                            placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/...")
        if _wh != _fc.get("webhook", ""):
            _fc["webhook"] = _wh
            with open(_cfg_path, "w") as _f:
                json.dump(_fc, _f, indent=2, ensure_ascii=False)
    else:
        st.info("推送已关闭")

    st.divider()
    st.caption(f"由 Hermes Agent 构建 · 2026 · {label}")

# ── 导航 ────────────────────────────────────────
st.title("📊 A 股交叉分析平台")
st.markdown("<p style='color:#888;font-size:1.1rem;'>选择功能模块，设置参数后点击查询按钮加载数据</p>", unsafe_allow_html=True)

cols = st.columns(10)
nav_links = [
    ("pages/01_单票分析.py", "📈 单票分析", "K线/技术指标/基本面/估值"),
    ("pages/02_多票对比.py", "🔍 多票对比", "多只股票横向比较"),
    ("pages/03_行业轮动.py", "🏭 行业轮动", "行业排行/成分股"),
    ("pages/04_筛选引擎.py", "🎯 筛选引擎", "估值×财务×行情筛选"),
    ("pages/05_资金流向.py", "💰 资金流向", "主力资金/个股时序"),
    ("pages/06_策略回测.py", "🧪 策略回测", "MA/MACD/RSI/布林策略回测"),
    ("pages/07_组合管理.py", "📊 组合管理", "组合净值/绩效/归因"),
    ("pages/08_龙虎榜追踪.py", "🏆 龙虎榜", "龙虎榜排行/个股追踪"),
    ("pages/09_数据浏览器.py", "📊 数据浏览器", "截面/时序/全市场均值"),
    ("pages/10_估值横截面.py", "📐 估值横截面", "估值排行/行业水位/散点"),
    ("pages/11_宏观数据.py", "📈 宏观数据", "CPI/PPI/PMI/GDP/M2/Shibor/LPR/美债"),
    ("pages/12_智能告警.py", "📡 智能告警", "估值/资金/技术/量价异动"),
    ("pages/13_产业链图谱.py", "🏭 产业链图谱", "锂电/光伏/半导体/AI算力/机器人/军工"),
    ("pages/14_多因子选股.py", "📊 多因子选股", "估值+质量+成长+动量 四维评分排名"),
        ("pages/15_盘后复盘.py", "盘后复盘", "每日收盘总结+行业排行+资金流向+飞书推送"),
        ("pages/16_条件盯盘.py", "条件盯盘", "自定义阈值+实时检查+飞书推送"),
        ("pages/17_AI智能诊股.py", "AI智能诊股", "因子+财务+资金+技术 全景诊断"),
        ("pages/18_交易信号看板.py", "交易信号", "因子+告警+证伪+反身 五位一体"),
        ("pages/19_风险分析.py", "📊 风险分析", "VaR/回撤/Beta/Sharpe/压力测试"),
                ("pages/20_实时行情.py", "📡 实时行情", "实时大盘+个股+全市场快照"),
        ("pages/21_国际行情.py", "🌍 国际行情", "港美股实时+外汇+全球指数"),
        ("pages/22_ESG评级.py", " ESG 评级", "E/S/G 三维评分+全市场筛选"),
        ("pages/23_研究报告.py", "📄 研究报告", "上传/搜索/查看 A 股研报"),
        ("pages/24_权限管理.py", "🔐 权限管理", "用户分级+功能矩阵+鉴权"),
         ]
for col_idx, (path, label, help_text), col in zip(range(len(nav_links)), nav_links, cols):
    with col:
        st.page_link(path, label=label, help=help_text)