"""
StockPulse 客户自助路由 — 订阅状态 / 交付记录 / 研报可见性

市场脉搏的"自助节拍"：客户自助查询服务。
"""
from typing import Optional

from fastapi import APIRouter, Query

from ..response import sp_success, sp_error, SpError
from ..services.self_service import get_status, list_deliveries, can_access
from ..services.reports import list_reports

router = APIRouter(tags=["客户自助 — 自助节拍"])


@router.get("/status", summary="订阅状态")
async def self_status(email: str = Query(..., description="客户邮箱")):
    """查询客户订阅状态：层级（admin/vip/basic）、有效期、功能权限"""
    if not email:
        return sp_error(SpError.INVALID_PARAMS, "需要 email 参数")
    status = get_status(email)
    res = dict(status)
    res["access"] = {
        "public_market": True,
        "reports": can_access(email, "reports"),
        "deliveries": can_access(email, "deliveries"),
        "portfolio": can_access(email, "portfolio"),
    }
    return sp_success(data=res)


@router.get("/deliveries", summary="交付记录")
async def self_deliveries(email: str = Query(..., description="客户邮箱"),
                          limit: int = Query(20, ge=1, le=100)):
    """客户已交付文件（研报 PDF/交互记录）"""
    if not email:
        return sp_error(SpError.INVALID_PARAMS, "需要 email 参数")
    if not can_access(email, "deliveries"):
        return sp_error(SpError.PROVIDER_ERR, "该层级无权查看交付记录（需年卡/管理）")
    return sp_success(data=list_deliveries(email, limit))


@router.get("/reports", summary="研报目录（自助）")
async def self_reports(email: str = Query(..., description="客户邮箱")):
    """客户可访问的研报目录（日报/周报，按层级放行）"""
    if not email:
        return sp_error(SpError.INVALID_PARAMS, "需要 email 参数")
    if not can_access(email, "reports"):
        return sp_error(SpError.PROVIDER_ERR, "该层级无权访问研报（需年卡/管理）")
    data = list_reports()
    data["tier"] = get_status(email).get("tier")
    data["total"] = len(data["daily"]) + len(data["weekly"])
    return sp_success(data=data)
