"""
StockPulse 条件筛选路由 — 多条件选股/创新高

市场脉搏的"筛选引擎"：从海量标的中精准定位。    
"""

from fastapi import APIRouter, Query
from typing import Optional

from ..data_service import SpDataService
from ..response import sp_success, sp_error, SpError

router = APIRouter(tags=["条件筛选 — 定位引擎"])


@router.get("/equity", summary="多条件选股")
async def screen_equity(
    pe_max: Optional[float] = Query(None, description="PE(TTM) 上限"),
    pe_min: Optional[float] = Query(None, description="PE(TTM) 下限"),
    pb_max: Optional[float] = Query(None, description="PB 上限"),
    pb_min: Optional[float] = Query(None, description="PB 下限"),
    roe_min: Optional[float] = Query(None, description="ROE 下限"),
    roe_max: Optional[float] = Query(None, description="ROE 上限"),
    total_mv_min: Optional[float] = Query(None, description="总市值下限(亿元)"),
    total_mv_max: Optional[float] = Query(None, description="总市值上限(亿元)"),
    industry: Optional[str] = Query(None, description="行业"),
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
):
    """多条件筛选 A 股

    根据估值、盈利能力、市值、行业条件筛选股票。
    """
    # 获取每日基本面最新数据
    df = SpDataService.query_raw(
        "daily_basic",
        """
        SELECT a.ts_code, a.trade_date, a.pe_ttm, a.pb,
               a.total_mv, a.circ_mv, a.turnover_rate
        FROM daily_basic a
        INNER JOIN (
            SELECT ts_code, MAX(trade_date) as max_date
            FROM daily_basic GROUP BY ts_code
        ) b ON a.ts_code = b.ts_code AND a.trade_date = b.max_date
        """,
    )

    if df.empty:
        return sp_error(SpError.NOT_FOUND, "暂无数据")

    # 获取股票名称和行业
    stocks = SpDataService.query_raw(
        "stock_basic",
        "SELECT ts_code, name, industry FROM stock_basic",
    )
    name_map = dict(zip(stocks["ts_code"], stocks["name"]))
    ind_map = dict(zip(stocks["ts_code"], stocks["industry"]))

    # 获取 ROE 数据
    roe_df = SpDataService.query_raw(
        "fina_indicator",
        """
        SELECT a.ts_code, a.roe
        FROM fina_indicator a
        INNER JOIN (
            SELECT ts_code, MAX(end_date) as max_date
            FROM fina_indicator GROUP BY ts_code
        ) b ON a.ts_code = b.ts_code AND a.end_date = b.max_date
        """,
    )
    roe_map = dict(zip(roe_df["ts_code"], roe_df["roe"]))

    # 筛选
    results = []
    for _, row in df.iterrows():
        code = row["ts_code"]

        pe = float(row["pe_ttm"]) if row["pe_ttm"] and row["pe_ttm"] > 0 else None
        pb = float(row["pb"]) if row["pb"] and row["pb"] > 0 else None
        mv = float(row["total_mv"]) if row["total_mv"] else None
        roe_val = float(roe_map.get(code)) if code in roe_map and roe_map.get(code) else None

        # 过滤
        if pe_max and (pe is None or pe > pe_max): continue
        if pe_min and (pe is None or pe < pe_min): continue
        if pb_max and (pb is None or pb > pb_max): continue
        if pb_min and (pb is None or pb < pb_min): continue
        if roe_min and (roe_val is None or roe_val < roe_min): continue
        if roe_max and (roe_val is None or roe_val > roe_max): continue
        if total_mv_min and (mv is None or mv < total_mv_min * 1e8): continue
        if total_mv_max and (mv is None or mv > total_mv_max * 1e8): continue
        if industry and ind_map.get(code) != industry: continue

        results.append({
            "ts_code": code,
            "name": name_map.get(code, ""),
            "industry": ind_map.get(code, ""),
            "pe_ttm": round(pe, 2) if pe else None,
            "pb": round(pb, 2) if pb else None,
            "roe": round(roe_val, 2) if roe_val else None,
            "total_mv": round(mv / 1e8, 2) if mv else None,
        })

        if len(results) >= limit:
            break

    return sp_success(data={
        "filters": {
            "pe_max": pe_max, "pe_min": pe_min,
            "pb_max": pb_max, "pb_min": pb_min,
            "roe_min": roe_min, "roe_max": roe_max,
            "total_mv_min": total_mv_min, "total_mv_max": total_mv_max,
            "industry": industry,
        },
        "records": results,
        "total": len(results),
    })