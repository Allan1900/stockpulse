"""
StockPulse 统一响应模型

品牌意涵: StockPulse = 市场脉搏
- 每一次 API 响应都是市场的一次「脉搏」
- code = 脉搏状态码（0=正常搏动）
- data = 脉搏携带的数据
- meta = 脉搏的节拍信息（总量、分页、时间戳）
"""

from pydantic import BaseModel
from typing import Any, Optional
from datetime import datetime
import time


# ── 血缘探测缓存（60s TTL，避免每请求查库） ──────────────
_LINEAGE_CACHE = {"ts": 0.0, "value": None}


def _probe_lineage() -> dict:
    """探测全局血缘（daily 最新交易日）— 兼容默认端点。

    data_date:     最新数据交易日 (YYYY-MM-DD)
    data_source:   postgresql（主库在线） | sqlite（降级，仅宏观）
    completeness:  0~1，主数据完整度（PG 在线=1.0；仅 SQLite 降级=0.2）
    """
    now = time.time()
    return _probe_table_lineage("daily", date_col="trade_date", global_fallback=True)


# ── 表级血缘探测（D1 2026-11-01：按表精确取最新日期，替代全局 daily 血缘） ──
_TABLE_LINEAGE_CACHE: dict[str, dict] = {}
_SQLITE_TIME_COLS = ("trade_date", "date", "month", "quarter", "period")


def _probe_sqlite_table_date(table, date_col=None):
    """在 SQLite 保留库中探测表最新日期 → (date_str, db_path)"""
    import sqlite3
    from ...paths import MACRO_DB, GLOBAL_MACRO_DB
    macro_db = str(MACRO_DB)
    global_db = str(GLOBAL_MACRO_DB)
    for db_path, tables_fn in ((macro_db, lambda t: True), (global_db, lambda t: True)):
        try:
            conn = sqlite3.connect(db_path)
            try:
                names = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                if table not in names:
                    continue
                cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
                candidates = [date_col] if date_col else []
                candidates += [c for c in _SQLITE_TIME_COLS if c in cols]
                for c in candidates:
                    if c not in cols:
                        continue
                    row = conn.execute(f"SELECT MAX(\"{c}\") FROM \"{table}\"").fetchone()
                    if row and row[0] is not None:
                        return str(row[0]), "sqlite"
            finally:
                conn.close()
        except Exception:
            continue
    return "", "sqlite"


def _probe_table_lineage(table: str, date_col: str = None, global_fallback: bool = False) -> dict:
    """按表探测血缘：data_date = 该表实际最新日期（保留原始格式），
    data_source = postgresql（表在 PG）| sqlite（表在 SQLite 保留库）。

    - PG 优先：连接 search_path=ashare,public，用 date_col（给定）或自动探测常见日期列
    - SQLite 降级：ashare_macro.db / ashare_global_macro.db
    - 缓存 per-table 60s
    """
    now = time.time()
    cached = _TABLE_LINEAGE_CACHE.get(table)
    if cached is not None and now - cached["ts"] < 60:
        return cached["value"]

    lineage = {"data_date": "", "data_source": "", "completeness": 0.0}
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost", dbname="ashare", user="zrall",
            options="-c search_path=ashare,public", connect_timeout=3)
        try:
            cur = conn.cursor()
            candidates = [date_col] if date_col else []
            candidates += [c for c in ("trade_date", "date", "month", "quarter", "period")
                           if c != date_col]
            seen = set()
            for c in candidates:
                if c in seen:
                    continue
                seen.add(c)
                try:
                    cur.execute(f"SELECT max(\"{c}\") FROM \"{table}\"")
                    row = cur.fetchone()
                    if row and row[0] is not None:
                        d = str(row[0])
                        if c == "trade_date" and len(d) == 8:
                            d = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
                        lineage["data_date"] = d
                        lineage["data_source"] = "postgresql"
                        lineage["completeness"] = 1.0
                        break
                except Exception:
                    continue
        finally:
            conn.close()
    except Exception:
        pass

    if not lineage["data_date"]:
        # SQLite 保留库（宏观）
        d, _ = _probe_sqlite_table_date(table, date_col)
        if d:
            lineage["data_date"] = d
            lineage["data_source"] = "sqlite"
            lineage["completeness"] = 0.6
        elif global_fallback:
            # 完全探测失败 → 回退全局 daily 血缘（保持兼容）
            return _probe_lineage_global()

    _TABLE_LINEAGE_CACHE[table] = {"ts": now, "value": lineage}
    return lineage


def _probe_lineage_global() -> dict:
    """全局 daily 血缘（旧 _probe_lineage 本体）"""
    now = time.time()
    if _LINEAGE_CACHE["value"] is not None and now - _LINEAGE_CACHE["ts"] < 60:
        return _LINEAGE_CACHE["value"]
    lineage = {"data_date": "", "data_source": "", "completeness": 0.0}
    try:
        import psycopg2
        conn = psycopg2.connect(
            host="localhost", dbname="ashare", user="zrall", connect_timeout=3)
        cur = conn.cursor()
        cur.execute("SELECT max(trade_date) FROM ashare.daily")
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            d = row[0]
            lineage["data_date"] = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            lineage["data_source"] = "postgresql"
            lineage["completeness"] = 1.0
    except Exception:
        lineage["data_source"] = "sqlite"
        lineage["completeness"] = 0.2
    _LINEAGE_CACHE.update(ts=now, value=lineage)
    return lineage


class SpMeta(BaseModel):
    """脉搏节拍 — 响应的元信息

    total:      数据总量（市场总脉搏数）
    page:       当前页码（第几次搏动）
    page_size:  每页大小（每次搏动量）
    total_pages:总页数（完整脉搏周期数）
    has_next:   是否还有后续搏动
    has_prev:   是否有前序搏动
    timestamp:  脉搏时间戳
    data_date:  数据血缘 — 最新数据交易日（YYYY-MM-DD）
    data_source:数据血缘 — postgresql / sqlite
    completeness:数据完整度（置信度 0~1）
    """
    total: int = 0
    page: int = 1
    page_size: int = 20
    total_pages: int = 0
    has_next: bool = False
    has_prev: bool = False
    timestamp: str = ""
    data_date: str = ""
    data_source: str = ""
    completeness: float = 0.0


class StockPulseResponse(BaseModel):
    """统一响应 — 市场的一次脉搏

    示例:
        {"code": 0, "message": "ok",
         "data": {"ts_code": "600519.SH", "records": [...]},
         "meta": {"total": 352, "page": 1, "page_size": 20, ...}}
    """
    code: int = 0
    message: str = "ok"
    data: Optional[Any] = None
    meta: Optional[SpMeta] = None


class SpError:
    """脉搏异常码 — 市场脉搏状态诊断"""
    SUCCESS = 0
    NOT_FOUND = 1001        # 数据不存在 — 市场无此标的
    INVALID_PARAMS = 1002   # 参数异常 — 查询信号畸变
    RATE_LIMIT = 1003       # 查询过频 — 脉搏太快
    PROVIDER_ERR = 1004     # 数据源异常 — 外部脉搏中断
    INTERNAL = 2000         # 内部异常 — 引擎故障
    DB_ERROR = 2001         # 数据库异常 — 存储脉搏异常


def _attach_lineage(meta, table: str = None, date_col: str = None):
    """把血缘探测结果补进 meta（兼容 SpMeta 实例与 dict 两种形态，不覆盖显式值）。
    table 指定时用表级血缘（更精确），否则用全局 daily 血缘。"""
    lineage = _probe_table_lineage(table, date_col=date_col) if table else _probe_lineage()
    if isinstance(meta, dict):
        meta.setdefault("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        meta.setdefault("data_date", lineage["data_date"])
        meta.setdefault("data_source", lineage["data_source"])
        meta.setdefault("completeness", lineage["completeness"])
    else:
        if not meta.timestamp:
            meta.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not meta.data_date:
            meta.data_date = lineage["data_date"]
        if not meta.data_source:
            meta.data_source = lineage["data_source"]
        if not meta.completeness:
            meta.completeness = lineage["completeness"]
    return meta


def sp_success(data=None, meta=None, message="ok", table: str = None, date_col: str = None):
    """生成一次成功的市场脉搏响应（自动附加血缘+置信度）。

    table/date_col 指定时使用表级血缘（data_date = 该表实际最新日期）。
    """
    if meta is None:
        meta = SpMeta()
    _attach_lineage(meta, table=table, date_col=date_col)
    return StockPulseResponse(code=SpError.SUCCESS, message=message,
                              data=data, meta=meta)


def sp_error(code: int, message: str, data=None):
    """生成一次异常的市场脉搏响应"""
    return StockPulseResponse(code=code, message=message, data=data)


def sp_paginate(df, page=1, page_size=20, table: str = None, date_col: str = None):
    """将 DataFrame 分页打包为脉搏节拍

    Args:
        df: 原始数据 DataFrame
        page: 当前页码（从1开始）
        page_size: 每页行数
        table/date_col: 表级血缘（data_date = 该表实际最新日期）

    Returns:
        StockPulseResponse: 包含分页数据和节拍元信息
    """
    total = len(df)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    end = start + page_size
    page_data = df.iloc[start:end]

    meta = SpMeta(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1,
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    return sp_success(data=page_data.to_dict(orient="records"), meta=meta, table=table, date_col=date_col)