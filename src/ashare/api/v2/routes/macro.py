"""
StockPulse 宏观经济路由 — CPI/PPI/PMI/GDP/M2/社融/Shibor/美债

市场脉搏的"宏观节拍"：经济基本面的整体韵律。
"""

from fastapi import APIRouter, Query
from typing import Optional

from ..data_service import SpDataService
from ..response import sp_success, sp_error, SpError

router = APIRouter(tags=["宏观经济 — 宏观节拍"])

MACRO_MAP = {
    "cpi":      {"table": "cn_cpi",      "name": "居民消费价格指数 (CPI)",      "date_col": "month"},
    "ppi":      {"table": "cn_ppi",      "name": "工业生产者出厂价格指数 (PPI)", "date_col": "month"},
    "pmi":      {"table": "cn_pmi",      "name": "采购经理指数 (PMI)",         "date_col": "month"},
    "gdp":      {"table": "cn_gdp",      "name": "国内生产总值 (GDP)",         "date_col": "quarter"},
    "m2":       {"table": "cn_m",        "name": "货币供应量 (M2)",            "date_col": "month"},
    "social_financing": {"table": "sf_month", "name": "社会融资规模",          "date_col": "month"},
    "shibor":   {"table": "shibor",      "name": "上海银行间同业拆放利率 (Shibor)", "date_col": "date"},
    "lpr":      {"table": "shibor_lpr",  "name": "贷款市场报价利率 (LPR)",     "date_col": "date"},
    "us_treasury": {"table": "us_tycr",  "name": "美国国债收益率",             "date_col": "date"},
}


@router.get("/{indicator}", summary="宏观经济指标查询")
async def get_macro(
    indicator: str,
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    limit: int = Query(100, ge=1, le=5000),
):
    """查询宏观经济指标数据

    支持指标: cpi, ppi, pmi, gdp, m2, social_financing, shibor, lpr, us_treasury
    """
    info = MACRO_MAP.get(indicator.lower())
    if not info:
        return sp_error(SpError.NOT_FOUND, f"未知指标: {indicator}")

    table = info["table"]
    date_col = info.get("date_col", "date")
    df = SpDataService.query_raw(
        table,
        f'SELECT * FROM "{table}" ORDER BY "{date_col}" DESC LIMIT ?',
        params=[limit],
    )

    # 日期过滤（使用正确的日期列名）
    if not df.empty:
        if start_date:
            s = start_date.replace("-", "")
            df = df[df[date_col].astype(str) >= s]
        if end_date:
            e = end_date.replace("-", "")
            df = df[df[date_col].astype(str) <= e]

    return sp_success(data={
        "indicator": indicator,
        "name": info["name"],
        "records": df.to_dict(orient="records") if not df.empty else [],
        "total": len(df),
    }, table=table, date_col=date_col)


@router.get("/list/all", summary="可查询的宏观指标列表")
async def get_macro_list():
    """列出所有可查询的宏观经济指标"""
    return sp_success(data=[
        {"key": k, "name": v["name"], "table": v["table"]}
        for k, v in MACRO_MAP.items()
    ])