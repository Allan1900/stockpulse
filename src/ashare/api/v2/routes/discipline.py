"""
StockPulse 交易纪律路由 — 陈江挺《炒股的智慧》执行纪律层
五层检查：环境过滤 / 标的信号 / 风险预算 / 退出管理 / 执行审计
"""
from fastapi import APIRouter, Query
from typing import Optional

from ..response import sp_success, sp_error, SpError
from ..services.trading_discipline import build_trading_plan, TOTAL_RISK_CAP_PCT

router = APIRouter(tags=["交易纪律 — 陈江挺执行纪律层(五层检查)"])


@router.get("/plan/{ts_code}", summary="交易机会纪律计划（五层，附风险预算与置信度）")
async def get_trading_plan(
    ts_code: str,
    total_capital: Optional[float] = Query(default=100000.0, description="总资金(元)，用于仓位反推"),
    current_risk_pct: Optional[float] = Query(default=0.0, description="组合当前已用风险敞口%"),
    date: Optional[str] = Query(None, description="交易日 YYYYMMDD（默认最新交易日）"),
    strict: Optional[bool] = Query(None, description="陈江挺框架开关：true=严格(L1空头一票否决) / false=宽松(L1只提示) / 缺省=跟随全局SP_DISCIPLINE_STRICT"),
):
    """陈江挺五层交易纪律计划：L1大市环境 / L2标的+临界点 / L3风险预算(止损+仓位反推) /
    L4退出管理 / 结论。回答"这笔交易是否值得参与"，不做公司价值判断。
    开关：strict=true 时大市空头直接判回避；strict=false 时输出参考计划并标注环境受限。"""
    try:
        result = build_trading_plan(ts_code, total_capital, current_risk_pct, date, strict)
    except Exception as e:
        return sp_error(SpError.INTERNAL, f"交易纪律引擎异常: {e}")
    return sp_success(data=result, message="交易纪律计划生成完成")


@router.get("/plan/portfolio/{pid}", summary="组合级风险敞口审计(风险预算聚合)")
async def get_portfolio_plan(
    pid: int,
    total_capital: Optional[float] = Query(default=100000.0, description="总资金(元)"),
    date: Optional[str] = Query(None, description="交易日 YYYYMMDD"),
):
    """组合级风险审计：聚合组合各持仓的止损价，按陈江挺风险预算逻辑计算
    每只持仓当前回撤风险（距止损幅度 × 仓位）与组合总风险敞口(vs 10%上限)。"""
    try:
        from ..services.market_regime import get_market_regime, DEFAULT_INDEX
        from ..services.signal_engine import _safe_float
        from ..services.portfolio import get_portfolio
        from ..data_service import SpDataService

        info, holdings = get_portfolio(pid)
        if info is None:
            return sp_error(SpError.NOT_FOUND, f"组合 {pid} 不存在")
        if holdings is None or holdings.empty:
            return sp_success(data={"pid": pid, "portfolio": info.to_dict(),
                                    "risk_items": [], "total_risk_pct": 0.0,
                                    "regime": get_market_regime(DEFAULT_INDEX, date).get("mkt_state"),
                                    "note": "组合暂无持仓"}, message="组合级风险审计完成")

        # 每只持仓：当前价 vs 止损价 → 单票风险% + 对组合风险贡献
        regime = get_market_regime(DEFAULT_INDEX, date)
        total_risk = 0.0
        risk_items = []
        for _, row in holdings.iterrows():
            code = row["ts_code"]
            stop = _safe_float(row.get("stop_price"))
            weight = _safe_float(row.get("weight_pct")) or 0.0
            # 当前最新收盘价
            px = SpDataService.query_raw(
                "daily", "SELECT close FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1", [code])
            cur = _safe_float(px["close"].iloc[0]) if not px.empty else None
            item = {
                "ts_code": code,
                "name": row.get("name", ""),
                "weight_pct": round(weight, 1),
                "has_stop": stop is not None,
            }
            if stop is not None and cur:
                stop_dist = (cur - stop) / cur * 100  # 距止损幅度%（正=还有回撤空间）
                item["current_price"] = round(cur, 2)
                item["stop_price"] = round(stop, 2)
                item["room_to_stop_pct"] = round(stop_dist, 2)
                # 若已跌破止损 → 风险敞口计为整仓
                if stop_dist <= 0:
                    item["flag"] = "已破止损(触发离场)"
                    contribution = weight
                else:
                    item["flag"] = "运行中"
                    contribution = weight * stop_dist / 100 * (1 if stop_dist < 20 else 0.2)
                item["risk_contribution_pct"] = round(min(contribution, TOTAL_RISK_CAP_PCT), 2)
                total_risk += contribution
            else:
                item["flag"] = "无止损/缺行情"
                item["current_price"] = round(cur, 2) if cur else None
                item["risk_contribution_pct"] = None
            risk_items.append(item)

        total_risk = min(total_risk, TOTAL_RISK_CAP_PCT)
        return sp_success(data={
            "pid": pid,
            "portfolio": info.to_dict(),
            "total_capital": total_capital,
            "risk_budget_cap_pct": TOTAL_RISK_CAP_PCT,
            "total_risk_pct": round(total_risk, 2),
            "within_cap": total_risk <= TOTAL_RISK_CAP_PCT,
            "regime": regime.get("mkt_state"),
            "regime_note": regime.get("note", ""),
            "risk_items": risk_items,
            "scope_note": "组合级风险审计：按陈江挺风险预算逻辑聚合止损风险，非价值判断。",
        }, message="组合级风险审计完成")
    except Exception as e:
        return sp_error(SpError.INTERNAL, f"组合风险审计异常: {e}")
