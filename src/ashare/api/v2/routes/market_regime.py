"""
StockPulse 市场状态路由 —「大市开关」
源自陈江挺《炒股的智慧》"大市不好不买"/"200日均线牛熊分界"。
"""
from fastapi import APIRouter, Query
from typing import Optional

from ..response import sp_success, sp_error, SpError
from ..services.market_regime import get_market_regime, DEFAULT_INDEX

router = APIRouter(tags=["市场状态 — 大市开关(陈江挺趋势框架)"])


@router.get("/regime", summary="大盘市场状态（上证MA200牛熊+MA60方向）")
async def get_regime(
    ts_code: Optional[str] = Query(default=DEFAULT_INDEX, description="指数代码(默认上证 000001.SH)"),
    date: Optional[str] = Query(None, description="交易日 YYYYMMDD（默认最新交易日）"),
):
    """大盘当前处于 可操作(多头)/观望(空头)/震荡 的市场状态，基于上证指数 MA200 长期牛熊
    分界 + MA60 中期生命线。回答"是否允许出手"，不做涨跌预测。"""
    try:
        result = get_market_regime(ts_code, date)
    except Exception as e:
        return sp_error(SpError.INTERNAL, f"市场状态引擎异常: {e}")
    if result.get("error"):
        return sp_error(SpError.NOT_FOUND, result["error"])
    return sp_success(data=result, message="市场状态计算完成")
