"""
StockPulse 组合管理路由 — Portfolio 组合创建/持仓/净值/绩效

市场脉搏的"资产脉搏"：组合层面的收益与风险视图。
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Body, Query, HTTPException

from ..response import sp_success, sp_error, SpError
from ..services.portfolio import (
    list_portfolios, create_portfolio, delete_portfolio, get_portfolio,
    add_holding, remove_holding, update_stop_price, calc_portfolio_nav, calc_portfolio_stats,
    brinson_attribution,
)

router = APIRouter(tags=["组合管理 — 资产脉搏"])


def _default_start() -> str:
    return (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")


@router.get("", summary="组合列表")
async def get_portfolios():
    """列出所有组合（含创建时间）"""
    df = list_portfolios()
    return sp_success(data={
        "total": len(df),
        "portfolios": df.to_dict(orient="records") if not df.empty else [],
    })


@router.post("", summary="创建组合")
async def post_portfolio(
    name: str = Body(..., description="组合名称"),
    description: str = Body("", description="描述"),
):
    """创建新组合"""
    pid, err = create_portfolio(name, description)
    if err:
        return sp_error(SpError.INTERNAL, f"创建失败: {err}")
    return sp_success(data={"id": pid, "name": name, "description": description})


@router.get("/{pid}", summary="组合详情（含持仓）")
async def get_portfolio_detail(pid: int):
    """组合基本信息 + 持仓列表（带名称/行业，按权重降序）"""
    info, holdings = get_portfolio(pid)
    if info is None:
        return sp_error(SpError.NOT_FOUND, f"组合 {pid} 不存在")
    return sp_success(data={
        "portfolio": info.to_dict(),
        "holdings": holdings.to_dict(orient="records") if holdings is not None and not holdings.empty else [],
        "holding_count": len(holdings) if holdings is not None else 0,
    })


@router.delete("/{pid}", summary="删除组合")
async def delete_portfolio_endpoint(pid: int):
    """删除组合（级联删除持仓）"""
    ok = delete_portfolio(pid)
    if not ok:
        return sp_error(SpError.NOT_FOUND, f"组合 {pid} 不存在")
    return sp_success(data={"deleted": True, "id": pid})


@router.post("/{pid}/holdings", summary="添加/更新持仓")
async def post_holding(
    pid: int,
    ts_code: str = Body(..., description="股票代码 如 600519.SH"),
    weight_pct: float = Body(..., description="权重 %（如 40 表示 40%）"),
    stop_price: Optional[float] = Body(None, description="止损价（陈江挺：进场前确定。可选）"),
):
    """添加或更新组合持仓（UPSERT），可附带止损价。"""
    ok, err = add_holding(pid, ts_code, weight_pct, stop_price)
    if err:
        return sp_error(SpError.INTERNAL, f"添加持仓失败: {err}")
    if not ok:
        return sp_error(SpError.NOT_FOUND, f"组合 {pid} 不存在")
    return sp_success(data={"pid": pid, "ts_code": ts_code, "weight_pct": weight_pct, "stop_price": stop_price})


@router.patch("/{pid}/holdings/{ts_code}/stop", summary="更新持仓止损价")
async def patch_stop_price(
    pid: int,
    ts_code: str,
    stop_price: float = Body(..., description="止损价"),
):
    """更新持仓止损价（陈江挺：进场前确定止损位 / 浮盈后上移至保本）。"""
    ok = update_stop_price(pid, ts_code, stop_price)
    if not ok:
        return sp_error(SpError.NOT_FOUND, f"持仓 {ts_code} 不在组合 {pid}")
    return sp_success(data={"pid": pid, "ts_code": ts_code, "stop_price": stop_price})


@router.delete("/{pid}/holdings/{ts_code}", summary="移除持仓")
async def delete_holding(pid: int, ts_code: str):
    """移除组合持仓"""
    ok = remove_holding(pid, ts_code)
    if not ok:
        return sp_error(SpError.NOT_FOUND, f"持仓 {ts_code} 不在组合 {pid}")
    return sp_success(data={"removed": True, "pid": pid, "ts_code": ts_code})


@router.get("/{pid}/nav", summary="组合净值曲线（对比沪深300）")
async def get_nav(
    pid: int,
    start_date: Optional[str] = Query(None, description="开始 YYYYMMDD（默认近365天）"),
    end_date: Optional[str] = Query(None, description="结束 YYYYMMDD（默认今日）"),
):
    """组合每日净值 NAV + 日均收益 + 沪深300基准 + 超额收益"""
    nav = calc_portfolio_nav(pid, start_date, end_date)
    if nav.empty:
        return sp_error(SpError.NOT_FOUND, f"组合 {pid} 无持仓或区间无行情数据")
    return sp_success(data={
        "pid": pid,
        "points": nav.to_dict(orient="records") if not nav.empty else [],
        "count": len(nav),
    })


@router.get("/{pid}/stats", summary="组合绩效统计")
async def get_stats(
    pid: int,
    start_date: Optional[str] = Query(None, description="开始 YYYYMMDD（默认近365天）"),
    end_date: Optional[str] = Query(None, description="结束 YYYYMMDD（默认今日）"),
):
    """组合绩效指标：年化收益/波动/夏普/最大回撤/胜率/超额/信息比率"""
    nav = calc_portfolio_nav(pid, start_date, end_date)
    if nav.empty:
        return sp_error(SpError.NOT_FOUND, f"组合 {pid} 无持仓或区间无行情数据")
    stats = calc_portfolio_stats(nav)
    return sp_success(data={"pid": pid, "stats": stats})


@router.get("/{pid}/attribution", summary="Brinson 归因（行业配置×选股）")
async def get_attribution(
    pid: int,
    start_date: Optional[str] = Query(None, description="开始 YYYYMMDD（默认近365天）"),
    end_date: Optional[str] = Query(None, description="结束 YYYYMMDD（默认今日）"),
):
    """Brinson 绩效归因：每只持仓的选股效应（个股收益 - 行业基准）"""
    df = brinson_attribution(pid, start_date, end_date)
    if df.empty:
        return sp_error(SpError.NOT_FOUND, f"组合 {pid} 无持仓或区间无行情数据")
    return sp_success(data={
        "pid": pid,
        "records": df.to_dict(orient="records") if not df.empty else [],
    })
