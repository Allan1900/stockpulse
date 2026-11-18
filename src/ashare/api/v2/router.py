"""StockPulse API v2 路由注册

注册所有 /sp-api/v2/ 端点，组织为清晰的业务域。
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .routes import stocks, equity, fundamental, moneyflow, lhb, holders
from .routes import index_data, macro, realtime, industry, screen, global_macro, philosophy, portfolio, reports, self
from .routes import diagnosis, signal_engine, market_regime, discipline

router = APIRouter(prefix="/sp-api/v2")

# ── Agent 集成协议 ──
@router.get("/agent.json", include_in_schema=False, tags=["Agent 集成协议"])
async def get_agent_json():
    """Agent 描述文件 — 让外部 AI Agent 发现和接入 StockPulse 数据能力"""
    return JSONResponse(content={
        "schema_version": "v1",
        "agent": {
            "name": "StockPulse Agent",
            "description": "A股市场数据智能 Agent | 提供行情/财务/资金流/龙虎榜/宏观/实时等全市场数据查询",
            "endpoints": {
                "query": "/sp-api/v2/agent/query",
            },
            "features": {
                "streaming": True,
                "stock_data": True,
                "fundamental_data": True,
                "moneyflow_data": True,
                "lhb_data": True,
                "macro_data": True,
                "realtime_data": True,
                "industry_analysis": True,
                "stock_screening": True,
                "philosophy_engine": True,
                "portfolio_management": True,
                "reports_ecosystem": True,
                "self_service": True,
                "ai_diagnosis": True,
                "signal_engine": True,
                "market_regime_engine": True,
                "trading_discipline_engine": True,
            },
            "tools": [
                {"name": "search_stocks", "params": {"query": "str", "limit": "int?"}},
                {"name": "get_daily", "params": {"ts_code": "str", "start_date": "str?", "end_date": "str?", "limit": "int?"}},
                {"name": "get_daily_basic", "params": {"ts_code": "str"}},
                {"name": "get_fundamentals", "params": {"ts_code": "str"}},
                {"name": "get_moneyflow", "params": {"ts_code": "str", "limit": "int?"}},
                {"name": "get_moneyflow_rank", "params": {"trade_date": "str", "top_n": "int?"}},
                {"name": "get_lhb", "params": {"trade_date": "str"}},
                {"name": "get_macro", "params": {"indicator": "str", "limit": "int?"}},
                {"name": "screen_stocks", "params": {"pe_max": "float?", "pb_max": "float?", "roe_min": "float?", "industry": "str?"}},
                {"name": "get_industry_performance", "params": {"top_n": "int?"}},
                {"name": "get_realtime", "params": {"ts_code": "str"}},
                {"name": "get_falsification", "params": {"ts_code": "str", "date": "str?"}},
                {"name": "get_reflexivity_stage", "params": {"ts_code": "str", "date": "str?"}},
                {"name": "get_portfolios", "params": {}},
                {"name": "get_portfolio_detail", "params": {"pid": "int"}},
                {"name": "portfolio_performance", "params": {"pid": "int", "start_date": "str?", "end_date": "str?"}},
                {"name": "get_reports", "params": {}},
                {"name": "get_report", "params": {"kind": "str", "date": "str", "limit": "int?"}},
                {"name": "get_self_status", "params": {"email": "str"}},
                {"name": "get_self_deliveries", "params": {"email": "str", "limit": "int?"}},
                {"name": "deep_diagnosis", "params": {"ts_code": "str", "date": "str?"}},
                {"name": "quick_diagnosis", "params": {"ts_code": "str", "date": "str?"}},
                {"name": "get_signal_analysis", "params": {"ts_code": "str", "date": "str?"}},
                {"name": "get_probability", "params": {"ts_code": "str", "date": "str?"}},
                {"name": "get_divergence", "params": {"ts_code": "str", "date": "str?"}},
                {"name": "backtest_signal", "params": {"ts_code": "str", "signal": "str?", "lookback": "int?", "horizon": "int?"}},
                {"name": "get_market_regime", "params": {"ts_code": "str?", "date": "str?"}},
                {"name": "get_trading_plan", "params": {"ts_code": "str", "total_capital": "float?", "current_risk_pct": "float?", "date": "str?"}},
            ],
        },
    })

# 股票信息
router.include_router(stocks.router, prefix="/stocks")

# 行情数据
router.include_router(equity.router, prefix="/equity")

# 财务数据
router.include_router(fundamental.router, prefix="/fundamental")

# 资金流向
router.include_router(moneyflow.router, prefix="/moneyflow")

# 龙虎榜
router.include_router(lhb.router, prefix="/lhb")

# 股东信息
router.include_router(holders.router, prefix="/holders")

# 指数数据
router.include_router(index_data.router, prefix="/index")

# 宏观经济
router.include_router(macro.router, prefix="/macro")

# 实时行情
router.include_router(realtime.router, prefix="/realtime")

# 行业分析
router.include_router(industry.router, prefix="/industry")

# 条件筛选
router.include_router(screen.router, prefix="/screen")

# 全球宏观
router.include_router(global_macro.router, prefix="/global_macro")

# 投资哲学引擎（Popper 证伪 + Soros 反身性）
router.include_router(philosophy.router, prefix="/philosophy")

# 组合管理（CRUD/NAV/绩效/归因）
router.include_router(portfolio.router, prefix="/portfolio")

# 研报生态（目录/详情/原文/PDF）
router.include_router(reports.router, prefix="/reports")

# 客户自助（订阅状态/交付记录/研报可见性）
router.include_router(self.router, prefix="/self")

# AI 深度诊股（多源交叉验证）
router.include_router(diagnosis.router, prefix="/diagnosis")

# 预测/信号引擎（技术信号/涨跌概率/量价背离/回测）
router.include_router(signal_engine.router, prefix="/signal")

# 市场状态（大市开关 — 陈江挺趋势框架）
router.include_router(market_regime.router, prefix="/market")

# 交易纪律（陈江挺执行纪律层 — 五层检查）
router.include_router(discipline.router, prefix="/discipline")