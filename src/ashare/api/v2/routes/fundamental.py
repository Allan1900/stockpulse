"""
StockPulse 财务数据路由 — 财务指标/利润表/资产负债表/现金流/摘要

市场脉搏的"基本面节拍"：公司的财务健康状况。
"""

from fastapi import APIRouter, Query
from typing import Optional

from ..data_service import SpDataService
from ..response import sp_error, sp_success, SpError

router = APIRouter(tags=["财务数据 — 基本面脉搏"])


@router.get("/fina_indicator/{ts_code}", summary="财务指标")
async def get_fina_indicator(
    ts_code: str,
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    fields: Optional[str] = Query(None, description="字段列表"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    """财务指标（ROE/毛利率/净利率/EPS/ROA 等）"""
    name = SpDataService.get_stock_name(ts_code.upper())
    result = SpDataService.query(
        "fina_indicator",
        filters={"ts_code": ts_code.upper()},
        page=page, page_size=page_size,
        sort_by="end_date", sort_order="desc",
        fields=fields,
        start_date=start_date, end_date=end_date,
        date_col="end_date",
    )
    if result.data and result.meta:
        result.data = {
            "ts_code": ts_code.upper(),
            "name": name or ts_code,
            "records": result.data,
        }
    return result


@router.get("/income/{ts_code}", summary="利润表")
async def get_income(
    ts_code: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    fields: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    """利润表（营收/营业利润/净利润）"""
    name = SpDataService.get_stock_name(ts_code.upper())
    result = SpDataService.query(
        "income",
        filters={"ts_code": ts_code.upper()},
        page=page, page_size=page_size,
        sort_by="end_date", sort_order="desc",
        fields=fields,
        start_date=start_date, end_date=end_date,
        date_col="end_date",
    )
    if result.data and result.meta:
        result.data = {
            "ts_code": ts_code.upper(),
            "name": name or ts_code,
            "records": result.data,
        }
    return result


@router.get("/balancesheet/{ts_code}", summary="资产负债表")
async def get_balancesheet(
    ts_code: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    fields: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    """资产负债表（总资产/总负债/净资产）"""
    name = SpDataService.get_stock_name(ts_code.upper())
    result = SpDataService.query(
        "balancesheet",
        filters={"ts_code": ts_code.upper()},
        page=page, page_size=page_size,
        sort_by="end_date", sort_order="desc",
        fields=fields,
        start_date=start_date, end_date=end_date,
        date_col="end_date",
    )
    if result.data and result.meta:
        result.data = {
            "ts_code": ts_code.upper(),
            "name": name or ts_code,
            "records": result.data,
        }
    return result


@router.get("/cashflow/{ts_code}", summary="现金流量表")
async def get_cashflow(
    ts_code: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    fields: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    """现金流量表（经营/投资/筹资现金流）"""
    name = SpDataService.get_stock_name(ts_code.upper())
    result = SpDataService.query(
        "cashflow",
        filters={"ts_code": ts_code.upper()},
        page=page, page_size=page_size,
        sort_by="end_date", sort_order="desc",
        fields=fields,
        start_date=start_date, end_date=end_date,
        date_col="end_date",
    )
    if result.data and result.meta:
        result.data = {
            "ts_code": ts_code.upper(),
            "name": name or ts_code,
            "records": result.data,
        }
    return result


@router.get("/summary/{ts_code}", summary="财务摘要")
async def get_fundamental_summary(
    ts_code: str,
):
    """聚合最新财报数据，生成财务摘要"""
    code = ts_code.upper()
    name = SpDataService.get_stock_name(code)

    # 取最新财务指标
    fina = SpDataService.query_raw(
        "fina_indicator",
        "SELECT * FROM fina_indicator WHERE ts_code=? "
        "ORDER BY end_date DESC LIMIT 2",
        params=[code],
    )
    # 取最新利润表
    income = SpDataService.query_raw(
        "income",
        "SELECT * FROM income WHERE ts_code=? AND report_type='1' "
        "ORDER BY end_date DESC LIMIT 2",
        params=[code],
    )

    summary = {"ts_code": code, "name": name or code}

    if not fina.empty:
        latest = fina.iloc[0]
        summary["latest"] = {
            "end_date": str(latest.get("end_date", "")),
            "eps": float(latest["eps"]) if latest.get("eps") else None,
            "roe": float(latest["roe"]) if latest.get("roe") else None,
            "gross_margin": float(latest["gross_margin"]) if latest.get("gross_margin") else None,
            "debt_to_assets": float(latest["debt_to_assets"]) if latest.get("debt_to_assets") else None,
            "roa": float(latest["roa"]) if latest.get("roa") else None,
        }
        # 趋势（同比变化）
        if len(fina) >= 2:
            prev = fina.iloc[1]
            if latest.get("roe") and prev.get("roe"):
                summary["roe_change"] = round(float(latest["roe"]) - float(prev["roe"]), 2)

    if not income.empty:
        latest_inc = income.iloc[0]
        summary["revenue"] = float(latest_inc["total_revenue"]) if latest_inc.get("total_revenue") else None
        summary["net_income"] = float(latest_inc["n_income_attr_p"]) if latest_inc.get("n_income_attr_p") else None

    return sp_success(data=summary)