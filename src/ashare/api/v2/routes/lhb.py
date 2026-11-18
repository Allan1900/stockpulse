"""
StockPulse 龙虎榜路由 — 每日上榜/个股上榜统计

市场脉搏的"异动信号"：资金博弈最激烈的地方。
"""

from fastapi import APIRouter, Query
from typing import Optional

from ..data_service import SpDataService
from ..response import sp_success, sp_error, SpError

router = APIRouter(tags=["龙虎榜 — 异动信号"])


@router.get("/{trade_date}", summary="某日龙虎榜")
async def get_top_list(
    trade_date: str,
    sort_by: str = Query("net_amount", description="排序字段"),
    sort_order: str = Query("desc", description="asc/desc"),
    limit: int = Query(50, ge=1, le=200),
):
    """指定交易日龙虎榜上榜股票"""
    td = trade_date.replace("-", "")
    df = SpDataService.query_raw(
        "top_list",
        f"SELECT * FROM top_list WHERE trade_date=? "
        f"ORDER BY {sort_by} {sort_order} LIMIT ?",
        params=[td, limit],
    )
    if df.empty:
        return sp_error(SpError.NOT_FOUND, f"暂无 {trade_date} 的龙虎榜数据")

    return sp_success(data={
        "trade_date": trade_date,
        "records": df.to_dict(orient="records"),
        "total": len(df),
    })


@router.get("/stats/{ts_code}", summary="个股上榜统计")
async def get_top_list_stats(
    ts_code: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """个股的历史上榜统计"""
    code = ts_code.upper()
    name = SpDataService.get_stock_name(code)

    where = "WHERE ts_code=?"
    params = [code]
    if start_date:
        where += " AND trade_date>=?"
        params.append(start_date.replace("-", ""))
    if end_date:
        where += " AND trade_date<=?"
        params.append(end_date.replace("-", ""))

    df = SpDataService.query_raw(
        "top_list",
        f"SELECT trade_date, name, pct_change, net_amount, reason "
        f"FROM top_list {where} ORDER BY trade_date DESC LIMIT 50",
        params=params,
    )
    return sp_success(data={
        "ts_code": code,
        "name": name or code,
        "records": df.to_dict(orient="records") if not df.empty else [],
        "total": len(df),
    })


@router.get("/dates/list", summary="有数据的日期列表")
async def get_top_list_dates():
    """返回所有有龙虎榜数据的日期"""
    df = SpDataService.query_raw(
        "top_list",
        "SELECT DISTINCT trade_date FROM top_list ORDER BY trade_date DESC",
    )
    dates = df["trade_date"].tolist() if not df.empty else []
    return sp_success(data={"trade_dates": dates, "total": len(dates)})