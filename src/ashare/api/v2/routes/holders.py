"""
StockPulse 股东信息路由 — 前十大股东/股东人数

市场脉搏的"持有者节拍"：谁在持有、筹码是否集中。
"""

from fastapi import APIRouter, Query
from typing import Optional

from ..data_service import SpDataService
from ..response import sp_success, sp_error, SpError

router = APIRouter(tags=["股东信息 — 持有者节拍"])


@router.get("/top10/{ts_code}", summary="前十大股东")
async def get_top10_holders(
    ts_code: str,
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
):
    """前十大股东持股明细"""
    code = ts_code.upper()
    name = SpDataService.get_stock_name(code)
    result = SpDataService.query(
        "top10_holders",
        filters={"ts_code": code},
        sort_by="end_date", sort_order="desc",
        start_date=start_date, end_date=end_date,
        date_col="end_date",
    )
    if result.data and result.meta:
        result.data = {
            "ts_code": code,
            "name": name or code,
            "records": result.data,
        }
    return result


@router.get("/holder_number/{ts_code}", summary="股东人数变化")
async def get_holder_number(
    ts_code: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """股东人数变化趋势"""
    code = ts_code.upper()
    name = SpDataService.get_stock_name(code)
    result = SpDataService.query(
        "stk_holdernumber",
        filters={"ts_code": code},
        sort_by="end_date", sort_order="desc",
        start_date=start_date, end_date=end_date,
        date_col="end_date",
    )
    if result.data and result.meta:
        result.data = {
            "ts_code": code,
            "name": name or code,
            "records": result.data,
        }
    return result