"""
StockPulse 预测/信号引擎路由 — 技术信号 + 涨跌概率 + 量价背离 + 历史回测
市场脉搏的"预测仪"：技术信号汇总、方向概率、背离预警、信号胜率考古。
"""
from fastapi import APIRouter, Query
from typing import Optional

from ..response import sp_success, sp_error, SpError
from ..services.signal_engine import (
    analyze_signals, predict_probability, detect_divergence, backtest_signal,
)

router = APIRouter(tags=["预测/信号引擎 — 技术信号/涨跌概率/量价背离/回测"])


@router.get("/analysis/{ts_code}", summary="技术信号汇总 + 指标快照")
async def get_signal_analysis(
    ts_code: str,
    date: Optional[str] = Query(None, description="交易日 YYYYMMDD（默认最新交易日）"),
):
    """技术信号汇总（MA/MACD/RSI/KDJ/BOLL/量价背离/连阳连阴）+ 最新指标快照。"""
    try:
        signals, snapshot, ctx = analyze_signals(ts_code, date)
    except Exception as e:
        return sp_error(SpError.INTERNAL, f"信号引擎异常: {e}")
    return sp_success(data={
        "ts_code": ts_code,
        "trade_date": ctx.get("trade_date") if ctx else None,
        "signals": signals,
        "indicators": snapshot,
    }, message="技术信号分析完成")


@router.get("/probability/{ts_code}", summary="涨跌概率估算（多因子模型）")
async def get_probability(
    ts_code: str,
    date: Optional[str] = Query(None, description="交易日 YYYYMMDD（默认最新交易日）"),
):
    """估算未来 5-20 个交易日看涨概率（0-100%），附因子归因。"""
    try:
        result = predict_probability(ts_code, date)
    except Exception as e:
        return sp_error(SpError.INTERNAL, f"概率模型异常: {e}")
    return sp_success(data=result, message="涨跌概率估算完成")


@router.get("/divergence/{ts_code}", summary="量价背离预警")
async def get_divergence(
    ts_code: str,
    date: Optional[str] = Query(None, description="交易日 YYYYMMDD（默认最新交易日）"),
):
    """量价背离预警：顶背离(价新高量萎缩) / 底背离(价新低但主力流入)。"""
    try:
        result = detect_divergence(ts_code, date)
    except Exception as e:
        return sp_error(SpError.INTERNAL, f"背离检测异常: {e}")
    return sp_success(data=result, message="量价背离检测完成")


@router.get("/backtest", summary="历史信号回测（胜率/平均收益）")
async def get_signal_backtest(
    ts_code: str = Query(..., description="股票代码，如 300750.SZ"),
    signal: str = Query("MACD金叉", description="信号类型: MACD金叉/死叉, MA金叉/死叉, RSI超卖/超买"),
    lookback: int = Query(500, ge=60, le=3000, description="回测窗口（交易日数）"),
    horizon: int = Query(10, ge=1, le=60, description="持有期（交易日数）"),
):
    """对指定技术信号做历史回测，统计其后 horizon 日胜率与平均收益。"""
    try:
        result = backtest_signal(ts_code, signal, lookback, horizon)
    except Exception as e:
        return sp_error(SpError.INTERNAL, f"回测引擎异常: {e}")
    return sp_success(data=result, message="历史信号回测完成")
