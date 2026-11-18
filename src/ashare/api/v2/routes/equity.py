"""
StockPulse 行情数据路由 — 日线/周线/月线/每日基本面

市场脉搏的"基础节拍"：股票的日常跳动轨迹。
"""

from fastapi import APIRouter, Query
from typing import Optional

from ..data_service import SpDataService
from ..response import sp_error, sp_success, SpError

router = APIRouter(tags=["行情数据 — 市场脉搏"])


@router.get("/daily", summary="日线行情查询")
async def get_daily(
    ts_code: Optional[str] = Query(None, description="股票代码"),
    symbol: Optional[str] = Query(None, description="简码"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    fields: Optional[str] = Query(None, description="字段列表"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
    limit: Optional[int] = Query(None, ge=1, le=5000),
):
    """A 股日线行情

    返回股票每日的开盘/收盘/最高/最低/涨跌幅/成交量/成交额。
    """
    if not ts_code and symbol:
        ts_code = SpDataService.resolve_symbol(symbol)
        if not ts_code:
            return sp_error(SpError.NOT_FOUND, f"未找到标的: {symbol}")

    filters = {}
    if ts_code:
        filters["ts_code"] = ts_code.upper()

    return SpDataService.query(
        "daily", filters=filters,
        page=page, page_size=page_size,
        sort_by="trade_date", sort_order="desc",
        fields=fields, limit=limit,
        start_date=start_date, end_date=end_date,
    )


@router.get("/daily/{ts_code}", summary="单只股票日线行情")
async def get_daily_by_code(
    ts_code: str,
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    fields: Optional[str] = Query(None, description="字段列表"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
):
    """获取单只股票的完整日线行情"""
    name = SpDataService.get_stock_name(ts_code.upper())
    result = SpDataService.query(
        "daily",
        filters={"ts_code": ts_code.upper()},
        page=page, page_size=page_size,
        sort_by="trade_date", sort_order="desc",
        fields=fields,
        start_date=start_date, end_date=end_date,
    )
    if result.data and result.meta:
        result.data = {
            "ts_code": ts_code.upper(),
            "name": name or ts_code,
            "records": result.data,
        }
    return result


@router.get("/daily_basic", summary="每日基本面指标")
async def get_daily_basic(
    ts_code: Optional[str] = Query(None, description="股票代码"),
    trade_date: Optional[str] = Query(None, description="交易日 YYYYMMDD"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    fields: Optional[str] = Query(None, description="字段列表"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    """每日基本面指标（PE/PB/PS/市值/换手率等）"""
    filters = {}
    if ts_code:
        filters["ts_code"] = ts_code.upper()
    if trade_date:
        filters["trade_date"] = trade_date

    return SpDataService.query(
        "daily_basic", filters=filters,
        page=page, page_size=page_size,
        sort_by="trade_date", sort_order="desc",
        fields=fields,
        start_date=start_date, end_date=end_date,
    )


@router.get("/weekly/{ts_code}", summary="周线行情")
async def get_weekly(
    ts_code: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    fields: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    """周线行情（从日线聚合）"""
    return SpDataService.query(
        "weekly",
        filters={"ts_code": ts_code.upper()},
        page=page, page_size=page_size,
        sort_by="trade_date", sort_order="desc",
        fields=fields,
        start_date=start_date, end_date=end_date,
    )


@router.get("/monthly/{ts_code}", summary="月线行情")
async def get_monthly(
    ts_code: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    fields: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    """月线行情（从日线聚合）"""
    return SpDataService.query(
        "monthly",
        filters={"ts_code": ts_code.upper()},
        page=page, page_size=page_size,
        sort_by="trade_date", sort_order="desc",
        fields=fields,
        start_date=start_date, end_date=end_date,
    )


@router.get("/trade_dates", summary="交易日列表")
async def get_trade_dates(
    ts_code: Optional[str] = Query(None, description="有数据的交易日"),
    year: Optional[str] = Query(None, description="年份"),
):
    """获取有交易数据的日期列表"""
    if ts_code:
        df = SpDataService.query_raw(
            "daily",
            "SELECT DISTINCT trade_date FROM daily WHERE ts_code=? "
            "ORDER BY trade_date DESC",
            params=[ts_code.upper()],
        )
        dates = df["trade_date"].tolist() if not df.empty else []
        return sp_success(data={"ts_code": ts_code.upper(),
                                "trade_dates": dates, "total": len(dates)})

    # 无 ts_code: 返回全年交易日
    df = SpDataService.query_raw(
        "stock_basic",  # 用 master 库
        "SELECT cal_date FROM trade_cal WHERE is_open=1 ORDER BY cal_date DESC",
    )
    dates = df["cal_date"].tolist() if not df.empty else []
    return sp_success(data={"trade_dates": dates, "total": len(dates)})