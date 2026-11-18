"""
StockPulse 投资哲学引擎路由 — Popper 证伪 + Soros 反身性
市场脉搏的"思想节拍"：买入/卖出前的证伪测试，繁荣/衰退阶段定位。
"""
from fastapi import APIRouter, Query
from typing import Optional

from ..data_service import SpDataService
from ..response import sp_success, sp_error, SpError
from ..services.philosophy import STAGES, falsify_buy, falsify_sell, identify_stage

router = APIRouter(tags=["投资哲学引擎 — Popper证伪 / Soros反身"])


def _resolve_date(date: Optional[str]) -> str:
    """交易日 YYYYMMDD（默认最新交易日），去横杠归一化"""
    if date:
        return date.replace("-", "")
    d = SpDataService.query_raw(
        "daily", "SELECT DISTINCT trade_date FROM daily ORDER BY trade_date DESC LIMIT 1")
    d0 = str(d.iloc[0]["trade_date"])
    return d0.replace("-", "") if "-" in d0 else d0


@router.get("/falsification/{ts_code}", summary="Popper 证伪测试（买入/卖出）")
async def get_falsification(
    ts_code: str,
    date: Optional[str] = Query(None, description="交易日 YYYYMMDD（默认最新交易日）"),
):
    """BUY/SELL 证伪测试 — 负分=证伪，正分=支持；附触发规则明细。"""
    d = _resolve_date(date)
    buy_score, buy_reasons = falsify_buy(ts_code, d)
    sell_score, sell_reasons = falsify_sell(ts_code, d)
    return sp_success(data={
        "ts_code": ts_code,
        "trade_date": d,
        "buy": {
            "score": round(buy_score, 2),
            "verdict": "被证伪" if buy_score < -0.30 else ("可疑" if buy_score < 0 else "未被证伪"),
            "rules": buy_reasons,
        },
        "sell": {
            "score": round(sell_score, 2),
            "verdict": "反驳成立" if sell_score > 0.30 else ("弱反驳" if sell_score > 0 else "无反驳"),
            "rules": sell_reasons,
        },
    })


@router.get("/reflexivity/{ts_code}", summary="Soros 反身性阶段识别")
async def get_reflexivity(
    ts_code: str,
    date: Optional[str] = Query(None, description="交易日 YYYYMMDD（默认最新交易日）"),
):
    """七阶段定位：潜伏→启动→加速→发散→狂欢→逆转→崩溃 + 发散指数。"""
    d = _resolve_date(date)
    info = identify_stage(ts_code, d)
    stage_def = next((s for s in STAGES if s["id"] == info["stage"]), {})
    return sp_success(data={
        "ts_code": ts_code,
        "trade_date": d,
        "stage": info["stage"],
        "stage_name": info["name"],
        "icon": info["icon"],
        "signal": info["signal"],
        "stage_guide": stage_def.get("signal", ""),
        "price_3m": info["price_3m"],
        "profit_yoy": info["profit_yoy"],
        "roe": info["roe"],
        "divergence_index": info["divergence_index"],
    })
