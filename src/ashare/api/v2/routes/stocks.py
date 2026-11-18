"""
StockPulse 股票信息路由 — 股票列表/搜索/信息

市场脉搏的"标的识别"：快速定位和检索 A 股标的。
"""

from fastapi import APIRouter, Query
from typing import Optional

from ..data_service import SpDataService
from ..response import sp_success, sp_error, SpError

router = APIRouter(tags=["股票信息 — 标的识别"])


@router.get("/", summary="股票列表")
async def list_stocks(
    exchange: Optional[str] = Query(None, description="交易所 SSE/SZSE"),
    market: Optional[str] = Query(None, description="市场板块 主板/创业板/科创板"),
    industry: Optional[str] = Query(None, description="行业"),
    list_status: str = Query("L", description="上市状态 L上市/D退市/P暂停"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
):
    """获取 A 股股票列表，支持多条件过滤"""
    filters = {}
    if exchange:
        filters["exchange"] = exchange
    if list_status:
        filters["list_status"] = list_status

    return SpDataService.query(
        "stock_basic", filters=filters,
        page=page, page_size=page_size,
        sort_by="ts_code", sort_order="asc",
    )


@router.get("/search", summary="搜索股票")
async def search_stocks(
    q: str = Query(..., description="搜索关键词（代码或名称）"),
    limit: int = Query(20, ge=1, le=100),
):
    """模糊搜索股票代码或名称"""
    df = SpDataService.query_raw(
        "stock_basic",
        "SELECT ts_code, symbol, name, industry, market, list_date "
        "FROM stock_basic WHERE list_status='L' AND "
        "(ts_code LIKE ? OR name LIKE ? OR symbol LIKE ?) "
        "ORDER BY ts_code LIMIT ?",
        params=[f"%{q}%", f"%{q}%", f"%{q}%", limit],
    )
    return sp_success(data={
        "query": q,
        "records": df.to_dict(orient="records") if not df.empty else [],
        "total": len(df),
    })


@router.get("/{ts_code}", summary="单只股票信息")
async def get_stock_info(
    ts_code: str,
):
    """获取单只股票基本信息"""
    code = ts_code.upper()
    df = SpDataService.query_raw(
        "stock_basic",
        "SELECT * FROM stock_basic WHERE ts_code=?",
        params=[code],
    )
    if df.empty:
        return sp_error(SpError.NOT_FOUND, f"未找到: {code}")
    return sp_success(data=df.iloc[0].to_dict())