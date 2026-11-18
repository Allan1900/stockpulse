"""
StockPulse 通用查询参数

每个数据端点共享的查询参数集合，确保一致的过滤、分页、排序体验。
"""

from fastapi import Query
from typing import Optional


class SpQueryParams:
    """StockPulse 通用查询参数 — 所有数据端点的标准查询信号

    每个参数都像是一个"信号过滤器"，从海量市场数据中筛选出需要的脉搏。
    """

    def __init__(
        self,
        # ── 标的识别 ──
        ts_code: Optional[str] = Query(
            None, description="股票代码 (如 600519.SH)"),
        symbol: Optional[str] = Query(
            None, description="简码 (如 600519)"),
        name: Optional[str] = Query(
            None, description="股票名称 (模糊匹配)"),

        # ── 时间窗口 ──
        trade_date: Optional[str] = Query(
            None, description="交易日 (YYYYMMDD)"),
        start_date: Optional[str] = Query(
            None, description="开始日期 (YYYYMMDD)"),
        end_date: Optional[str] = Query(
            None, description="结束日期 (YYYYMMDD)"),

        # ── 字段选择 ──
        fields: Optional[str] = Query(
            None, description="返回字段，逗号分隔 (如 close,vol,pct_chg)"),

        # ── 分页 ──
        page: int = Query(1, ge=1, description="页码"),
        page_size: int = Query(20, ge=1, le=1000, description="每页行数"),

        # ── 排序 ──
        sort_by: Optional[str] = Query(
            None, description="排序字段"),
        sort_order: str = Query("desc", description="排序方向: asc/desc"),

        # ── 快捷限制（无分页时使用） ──
        limit: Optional[int] = Query(
            None, ge=1, le=10000, description="返回行数上限"),
    ):
        self.ts_code = ts_code
        self.symbol = symbol
        self.name = name
        self.trade_date = trade_date
        self.start_date = start_date
        self.end_date = end_date
        self.fields = fields
        self.page = page
        self.page_size = page_size
        self.sort_by = sort_by
        self.sort_order = sort_order
        self.limit = limit

    def to_filters(self) -> dict:
        """将查询参数转为过滤条件 dict（非 None 值）"""
        filters = {}
        if self.ts_code:
            filters["ts_code"] = self.ts_code.upper()
        if self.symbol:
            filters["symbol"] = self.symbol
        if self.trade_date:
            filters["trade_date"] = self.trade_date.replace("-", "")
        return filters

    def date_range(self) -> tuple:
        """返回标准化的日期范围 (start, end)"""
        start = self.start_date.replace("-", "") if self.start_date else None
        end = self.end_date.replace("-", "") if self.end_date else None
        return start, end