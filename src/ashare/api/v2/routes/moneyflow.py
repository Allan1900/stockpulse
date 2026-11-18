"""
StockPulse 资金流向路由 — 个股资金流/全市场排行/汇总

市场脉搏的"资金脉动"：谁在买、谁在卖、资金流向哪里。
"""

from fastapi import APIRouter, Query
from typing import Optional

from ..data_service import SpDataService
from ..response import sp_success, sp_error, SpError

router = APIRouter(tags=["资金流向 — 资金脉动"])


@router.get("/{ts_code}", summary="个股资金流向")
async def get_moneyflow(
    ts_code: str,
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    fields: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    """个股资金流向（主力/散户/超大单/大单净流入）"""
    name = SpDataService.get_stock_name(ts_code.upper())
    result = SpDataService.query(
        "moneyflow",
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


@router.get("/rank/{trade_date}", summary="全市场资金排行")
async def get_moneyflow_rank(
    trade_date: str,
    sort_by: str = Query("net_mf_amount", description="排序字段"),
    top_n: int = Query(30, ge=5, le=100),
):
    """指定交易日全市场资金净流入/流出排行"""
    df = SpDataService.query_raw(
        "moneyflow",
        f"SELECT ts_code, trade_date, buy_sm_vol, sell_sm_vol, "
        f"buy_md_vol, sell_md_vol, buy_lg_vol, sell_lg_vol, "
        f"buy_elg_vol, sell_elg_vol, net_mf_vol, net_mf_amount "
        f"FROM moneyflow WHERE trade_date=? "
        f"ORDER BY {sort_by} DESC LIMIT ?",
        params=[trade_date.replace("-", ""), top_n],
    )
    if df.empty:
        return sp_error(SpError.NOT_FOUND, f"暂无 {trade_date} 的资金排行数据")

    # 附上股票名称
    stock_names = {}
    for _, row in df.iterrows():
        code = row["ts_code"]
        if code not in stock_names:
            stock_names[code] = SpDataService.get_stock_name(code)

    records = df.to_dict(orient="records")
    for r in records:
        r["name"] = stock_names.get(r["ts_code"], "")

    return sp_success(data={
        "trade_date": trade_date,
        "sort_by": sort_by,
        "records": records,
        "total": len(records),
    })


@router.get("/market_summary/{trade_date}", summary="市场资金汇总")
async def get_market_summary(
    trade_date: str,
):
    """全市场资金流向汇总（净流入总额/各类型资金）"""
    df = SpDataService.query_raw(
        "moneyflow",
        "SELECT "
        "COUNT(DISTINCT ts_code) as stock_count, "
        "SUM(net_mf_amount) as total_net_amount, "
        "SUM(buy_elg_vol) as total_buy_elg, "
        "SUM(sell_elg_vol) as total_sell_elg, "
        "SUM(buy_lg_vol) as total_buy_lg, "
        "SUM(sell_lg_vol) as total_sell_lg "
        "FROM moneyflow WHERE trade_date=?",
        params=[trade_date.replace("-", "")],
    )
    if df.empty:
        return sp_error(SpError.NOT_FOUND, f"暂无 {trade_date} 的资金汇总数据")

    return sp_success(data={
        "trade_date": trade_date,
        "total_net_amount": float(df.iloc[0]["total_net_amount"]) if df.iloc[0]["total_net_amount"] else 0,
        "stock_count": int(df.iloc[0]["stock_count"]) if df.iloc[0]["stock_count"] else 0,
    })