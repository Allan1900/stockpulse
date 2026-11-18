"""
StockPulse AI 深度诊股路由 — 多源交叉验证 深度诊断报告
市场脉搏的"诊疗台"：财务/资金/技术/宏观 四维度 + 哲学仲裁，带置信度。
"""
from fastapi import APIRouter, Query
from typing import Optional

from ..response import sp_success, sp_error, SpError
from ..services.diagnosis import deep_diagnosis, quick_score

router = APIRouter(tags=["AI 深度诊股 — 多源交叉验证"])


@router.get("/deep/{ts_code}", summary="AI 深度诊股报告（4维度+哲学+置信度）")
async def get_deep_diagnosis(
    ts_code: str,
    date: Optional[str] = Query(None, description="交易日 YYYYMMDD（默认最新交易日）"),
):
    """多源交叉验证的深度个股诊断：财务/资金/技术/宏观四维度独立评分 +
    Popper 证伪否决 + Soros 反身阶段，输出综合评分(0-100)、观点、置信度与证据清单。"""
    try:
        result = deep_diagnosis(ts_code, date)
    except Exception as e:
        return sp_error(SpError.INTERNAL, f"诊断引擎异常: {e}")
    return sp_success(data=result, message="AI 深度诊股完成")


@router.get("/{ts_code}", summary="AI 诊股简版评分（快速）")
async def get_quick_diagnosis(
    ts_code: str,
    date: Optional[str] = Query(None, description="交易日 YYYYMMDD（默认最新交易日）"),
):
    """简版快速评分 — 综合分+观点+置信度，供快速决策/MCP 调用。"""
    try:
        result = quick_score(ts_code, date)
    except Exception as e:
        return sp_error(SpError.INTERNAL, f"评分引擎异常: {e}")
    return sp_success(data=result, message="AI 诊股简版完成")
