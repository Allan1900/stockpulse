"""
StockPulse 指数数据路由 — 指数日线/成分股

市场脉搏的"市场基准节拍"：大盘/板块的整体跳动。
"""

from fastapi import APIRouter, Query
from typing import Optional

from ..data_service import SpDataService
from ..response import sp_success

router = APIRouter(tags=["指数数据 — 市场基准"])


@router.get("/daily/{ts_code}", summary="指数日线行情")
async def get_index_daily(
    ts_code: str,
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    fields: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
):
    """指数日线行情（上证综指=000001.SH，创业板指=399006.SZ 等）"""
    result = SpDataService.query(
        "index_daily",
        filters={"ts_code": ts_code.upper()},
        page=page, page_size=page_size,
        sort_by="trade_date", sort_order="desc",
        fields=fields,
        start_date=start_date, end_date=end_date,
    )
    if result.data and result.meta:
        # 查询指数名称
        df = SpDataService.query_raw(
            "index_basic",
            "SELECT name FROM index_basic WHERE ts_code=?",
            params=[ts_code.upper()],
        )
        index_name = df.iloc[0]["name"] if not df.empty else ts_code
        result.data = {
            "ts_code": ts_code.upper(),
            "name": index_name,
            "records": result.data,
        }
    return result


@router.get("/constituents/{ts_code}", summary="指数成分股")
async def get_index_constituents(
    ts_code: str,
):
    """指数成分股列表（沪深300=000300.SH，中证500=000905.SH 等）"""
    # 指数成分股存储在 industry_classify 表中
    df = SpDataService.query_raw(
        "industry_classify",
        "SELECT * FROM industry_classify WHERE index_code=? ORDER BY industry_code",
        params=[ts_code.upper()],
    )
    if not df.empty:
        records = df.to_dict(orient="records")
        # 附上股票名称
        for r in records:
            name = SpDataService.get_stock_name(r.get("industry_code", ""))
            if name:
                r["stock_name"] = name
    else:
        records = []

    # 查询指数名称
    idx_df = SpDataService.query_raw(
        "index_basic",
        "SELECT name FROM index_basic WHERE ts_code=?",
        params=[ts_code.upper()],
    )
    index_name = idx_df.iloc[0]["name"] if not idx_df.empty else ts_code

    return sp_success(data={
        "ts_code": ts_code.upper(),
        "name": index_name,
        "constituents": records,
        "total": len(records),
    })


@router.get("/list", summary="可查询的指数列表")
async def get_index_list():
    """所有可供查询的指数列表"""
    df = SpDataService.query_raw(
        "index_basic",
        "SELECT ts_code, name, market, index_type FROM index_basic ORDER BY ts_code",
    )
    return sp_success(data=df.to_dict(orient="records") if not df.empty else [])