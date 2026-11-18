"""
StockPulse 研报生态路由 — 研报目录/详情/PDF 下载

市场脉搏的"研报节拍"：每日/每周研究产出检索。
数据源：本地研报产出目录（~/market-daily、~/market-weekly）。
"""
from pathlib import Path

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

from ..response import sp_success, sp_error, SpError
from ..services.reports import list_reports, get_report, _find

router = APIRouter(tags=["研报生态 — 研报节拍"])


@router.get("", summary="研报目录（日报+周报）")
async def get_reports_index():
    """扫描研报产出目录，返回日报/周报列表（按日期倒序）"""
    data = list_reports()
    data["total"] = len(data["daily"]) + len(data["weekly"])
    return sp_success(data=data)


@router.get("/{kind}/{date}", summary="研报详情（正文预览）")
async def get_report_detail(kind: str, date: str,
                            limit: int = Query(4000, ge=200, le=20000)):
    """研报正文预览（markdown 前 N 字符，默认 4000）
    kind: daily 或 weekly；date: daily=YYYYMMDD / weekly=周目录名（如 2026-W44）
    """
    if kind not in ("daily", "weekly"):
        return sp_error(SpError.INVALID_PARAMS, "kind 必须为 daily 或 weekly")
    data = get_report(kind, date, limit)
    if not data:
        return sp_error(SpError.NOT_FOUND, f"研报不存在: {kind}/{date}")
    return sp_success(data=data)


@router.get("/{kind}/{date}/raw", summary="研报原文（完整 markdown 文本）")
async def get_report_raw(kind: str, date: str):
    """研报完整 markdown 原文（供 AI 摘要/引用）"""
    if kind not in ("daily", "weekly"):
        return sp_error(SpError.INVALID_PARAMS, "kind 必须为 daily 或 weekly")
    found = _find(kind, date)
    if not found:
        return sp_error(SpError.NOT_FOUND, f"研报不存在: {kind}/{date}")
    md_path, _ = found
    return PlainTextResponse(content=md_path.read_text(encoding="utf-8", errors="replace"),
                             media_type="text/markdown")


@router.get("/{kind}/{date}/pdf", summary="研报 PDF 下载")
async def get_report_pdf(kind: str, date: str):
    """研报 PDF 文件（日报/周报 PDF）"""
    if kind not in ("daily", "weekly"):
        return sp_error(SpError.INVALID_PARAMS, "kind 必须为 daily 或 weekly")
    found = _find(kind, date)
    if not found:
        return sp_error(SpError.NOT_FOUND, f"研报不存在: {kind}/{date}")
    md_path, pdf_path = found
    if not pdf_path:
        return sp_error(SpError.NOT_FOUND, f"研报 {kind}/{date} 无 PDF（仅 markdown）")
    return FileResponse(str(pdf_path), filename=Path(pdf_path).name,
                        media_type="application/pdf")
