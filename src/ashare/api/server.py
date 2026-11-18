"""
StockPulse API Server — 市场脉搏 REST API 服务

品牌: StockPulse = 市场脉搏
v1 (遗留): /api/v1/* — 保持向后兼容
v2 (当前): /sp-api/v2/* — 标准化的 StockPulse 脉搏响应
"""

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import uvicorn

from ..config import get_config

# ── FastAPI 应用 ──
app = FastAPI(
    title="StockPulse API",
    version="2.0.0",
    description="""StockPulse = 市场脉搏
每一次 API 响应都是市场的一次"脉搏"，携带数据、状态和节拍(元信息)。

## 端点速览

| 前缀 | 内容 |
|------|------|
| /sp-api/v2/* | 【推荐】标准化 StockPulse 响应 |
| /api/v1/* | 遗留端点，保持向后兼容 |
| /sp-api/system/* | 系统监控 |
| /docs | 交互式 API 文档 |
""",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 注册路由 ──
# StockPulse v2 (新架构)
from .v2.router import router as v2_router
app.include_router(v2_router)

# ── PWA 终端 (2026-11-01 P2) ──
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/app", StaticFiles(directory=str(_STATIC_DIR), html=True), name="pwa")

# ── 系统监控 ──
@app.get("/sp-api/system/health", tags=["系统监控"])
async def system_health():
    """系统健康检查 — 数据库连接状态（已退役库不计入在线/故障统计）"""
    from .v2.data_service import SpDataService
    db_stats = SpDataService.get_db_stats()
    active = {k: v for k, v in db_stats.items() if not v.get("retired")}
    online = sum(1 for v in active.values() if v.get("alive"))
    retired = len(db_stats) - len(active)
    return {
        "service": "StockPulse",
        "version": "2.0.0",
        "status": "ok",
        "db_summary": {
            "total": len(active),
            "online": online,
            "down": len(active) - online,
            "retired": retired,
        },
        "databases": db_stats,
    }

# ── 根端点 ──
@app.get("/")
def root():
    return {
        "service": "StockPulse",
        "version": "2.0.0",
        "docs": "/docs",
        "v2_endpoints": "/sp-api/v2",
        "v1_legacy": "/api/v1",
        "pwa_terminal": "/app/",
    }


# ── v1 遗留端点 (向后兼容) ──
@app.get("/api/v1/status")
def api_status():
    """数据库状态 (v1 遗留)"""
    from ..db.status import get_stock_count, get_trading_days_count
    return {
        "stocks": get_stock_count(),
        "trading_days": get_trading_days_count(),
    }


@app.get("/api/v1/stocks")
def list_stocks(q: str = Query(None, description="搜索股票代码或名称")):
    """股票列表 (v1 遗留)"""
    from ..db.query import get_stock_list
    df = get_stock_list()
    if q:
        df = df[df["ts_code"].str.contains(q, case=False) |
                df["name"].str.contains(q, case=False)]
    records = df.to_dict(orient="records")
    return {"total": len(records), "stocks": records}


@app.get("/api/v1/daily/{ts_code}")
def get_daily(ts_code: str,
              start: str = Query(None, description="开始日期 YYYYMMDD"),
              end: str = Query(None, description="结束日期 YYYYMMDD"),
              limit: int = Query(100, le=1000)):
    """日线行情 (v1 遗留)"""
    from ..db.query import query_single_stock
    df = query_single_stock(ts_code, "*", start, end)
    if df.empty:
        raise HTTPException(404, f"无数据: {ts_code}")
    return {"ts_code": ts_code, "total": len(df),
            "data": df.tail(limit).to_dict(orient="records")}


@app.get("/api/v1/financial/{ts_code}")
def get_financial(ts_code: str,
                  start: str = Query(None),
                  end: str = Query(None)):
    """财务数据 (v1 遗留)"""
    from ..db.query import get_financial, get_balancesheet, get_cashflow, get_income
    return {
        "ts_code": ts_code,
        "fina_indicator": get_financial(ts_code, start, end).to_dict(orient="records"),
        "income": get_income(ts_code, start, end).to_dict(orient="records"),
        "balancesheet": get_balancesheet(ts_code, start, end).to_dict(orient="records"),
        "cashflow": get_cashflow(ts_code, start, end).to_dict(orient="records"),
    }


@app.get("/api/v1/moneyflow/{ts_code}")
def get_moneyflow(ts_code: str,
                  start: str = Query(None),
                  end: str = Query(None)):
    """资金流向 (v1 遗留)"""
    from ..db.query import get_moneyflow
    df = get_moneyflow(ts_code, start, end)
    return {"ts_code": ts_code, "total": len(df),
            "data": df.to_dict(orient="records")}


@app.get("/api/v1/industries")
def get_industries(start: str = Query(None),
                   end: str = Query(None),
                   top_n: int = Query(15, le=30)):
    """行业涨跌排行 (v1 遗留)"""
    from ..db.query import get_industry_performance
    df = get_industry_performance(start, end, top_n)
    if df.empty:
        raise HTTPException(404, "无数据")
    return df.to_dict(orient="records")


@app.get("/api/v1/lhb/{trade_date}")
def get_lhb(trade_date: str):
    """龙虎榜 (v1 遗留)"""
    from ..db.query import get_top_list_by_date
    df = get_top_list_by_date(trade_date)
    return {"trade_date": trade_date, "total": len(df),
            "data": df.to_dict(orient="records")}


@app.get("/api/v1/macro/{table}")
def get_macro(table: str, start: str = Query(None), end: str = Query(None)):
    """宏观经济数据 (v1 遗留)"""
    from ..db.query import get_macro
    df = get_macro(table, start, end)
    if df.empty:
        raise HTTPException(404, f"无数据或表不存在: {table}")
    return {"table": table, "total": len(df),
            "data": df.to_dict(orient="records")}


@app.get("/api/v1/screen")
def screen_stocks(pe_max: float = Query(None),
                  pb_max: float = Query(None),
                  roe_min: float = Query(None),
                  industry: str = Query(None),
                  limit: int = Query(50, le=200)):
    """股票筛选 (v1 遗留)"""
    from ..db.query import get_stock_list, sql
    stocks = get_stock_list()
    results = []

    for _, row in stocks.head(2000).iterrows():
        code = row["ts_code"]
        row_data = sql("daily",
            "SELECT pe_ttm, pb FROM daily_basic WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1",
            params=[code])
        if row_data.empty:
            continue
        pe = row_data.iloc[0]["pe_ttm"]
        pb = row_data.iloc[0]["pb"]

        if pe_max and (pe is None or pe > pe_max):
            continue
        if pb_max and (pb is None or pb > pb_max):
            continue
        if industry and row["industry"] != industry:
            continue

        results.append({
            "ts_code": code,
            "name": row["name"],
            "industry": row["industry"],
            "pe_ttm": pe,
            "pb": pb,
        })

        if len(results) >= limit:
            break

    return {"total": len(results), "stocks": results}


def run_server(host="0.0.0.0", port=8000):
    """启动 StockPulse API 服务器"""
    print("╔══════════════════════════════════════════╗")
    print("║        StockPulse API · 市场脉搏         ║")
    print("╠══════════════════════════════════════════╣")
    print(f"║  API:    http://{host}:{port}/sp-api/v2  ║")
    print(f"║  Docs:   http://{host}:{port}/docs       ║")
    print(f"║  Legacy: http://{host}:{port}/api/v1     ║")
    print("╚══════════════════════════════════════════╝")
    uvicorn.run(app, host=host, port=port)