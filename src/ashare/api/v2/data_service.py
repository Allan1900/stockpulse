"""
StockPulse 数据服务层 — 市场脉搏的数据引擎（v2.1 双后端版）

统一查询入口，封装跨库查询、分页、字段过滤、排序。
所有 /sp-api/v2/ 端点通过此层获取数据。

## v2.1 双后端架构（2026-10-31）

数据管道已从 SQLite 迁移到 PostgreSQL（daily_update.py → PG），
本层按「表级路由」自动选择后端：

- **PG 优先**：daily / daily_basic / moneyflow / index_daily / top_list /
  top10_holders / stk_holdernumber / stock_basic / trade_cal /
  fina_indicator / income / balancesheet / cashflow / hsgt_top10 /
  hsgt_moneyflow / index_basic / macro_data / weekly / monthly …
- **SQLite 降级**：PG 中不存在的表（fred_series / wb_data / cn_* 宏观表等）
  继续走原 SQLite 库，保证端点不中断。

## 性能优化策略

### 问题：全表 COUNT 慢
大表（daily 840万行 PG / 190万行 SQLite）的 COUNT(*) 需要全表扫描。
→ 对于无过滤条件的分页，使用 capped-count 模式：
   COUNT 上限设为 page_size*2+1，超出则标记 has_more=True 但不给出精确总数

### 问题：无索引过虑慢
→ 为 trade_date 列创建索引，加速日期范围查询和排序

### 内存（SQLite 模式）
→ WAL 模式，读写不互斥
→ mmap 大文件（daily 2GB, moneyflow 1GB）
→ cache_size 按文件大小配置
"""

import sqlite3
import threading
import time
import os
from typing import Optional
import pandas as pd

from ...config import db_path
from ...db.schema import ALL_SCHEMAS
from .response import sp_success, sp_paginate, sp_error, SpError, StockPulseResponse


# ── PostgreSQL 后端探测 ──────────────────────────
try:
    import psycopg2
    _PG_CONFIG = {
        "host": os.environ.get("PGHOST", "localhost"),
        "dbname": os.environ.get("PGDATABASE", "ashare"),
        "user": os.environ.get("PGUSER", "zrall"),
        "options": "-c search_path=ashare,public",
    }
    _test = psycopg2.connect(**_PG_CONFIG)
    _test.close()
    _PG_AVAILABLE = True
except Exception:
    _PG_AVAILABLE = False

# PG 中存在的表 — 这些表走 PG 后端；其余表走 SQLite 降级
PG_TABLES = {
    "daily", "daily_basic", "moneyflow", "index_daily", "index_basic",
    "top_list", "top10_holders", "stk_holdernumber",
    "stock_basic", "stock_delisted", "trade_cal",
    "fina_indicator", "income", "balancesheet", "cashflow",
    "income_basic",
    "hsgt_moneyflow", "hsgt_top10",
    "macro_data", "macro_meta", "industry_classify",
    "portfolio", "portfolio_holding", "portfolio_trade",
    "weekly", "monthly",
}

# ── 按数据库大小调优的连接配置（SQLite 模式） ──
DB_TUNE = {
    "daily":     {"cache": -128000, "mmap": 2147483648, "sync": "OFF", "label": "日线(PG)"},
    "moneyflow": {"cache": -64000,  "mmap": 1073741824, "sync": "OFF", "label": "资金流(PG)"},
    "financial": {"cache": -64000,  "mmap": 536870912,  "sync": "NORMAL", "label": "财务(PG)"},
    "holders":   {"cache": -32000,  "mmap": 536870912,  "sync": "NORMAL", "label": "股东(PG)"},
    "period":    {"cache": -32000,  "mmap": 536870912,  "sync": "NORMAL", "label": "周期(旧SQLite)",
                  "retired": True,
                  "retired_note": "已迁移至 PG 物化视图 weekly/monthly；SQLite 快照归档 archive_sqlite_20261031/"},
    "lhb":       {"cache": -8000,   "mmap": 0,          "sync": "NORMAL", "label": "龙虎榜(PG)"},
    "index":     {"cache": -8000,   "mmap": 0,          "sync": "NORMAL", "label": "指数(PG)"},
    "master":    {"cache": -8000,   "mmap": 0,          "sync": "NORMAL", "label": "基础(PG)"},
    "macro":     {"cache": -8000,   "mmap": 0,          "sync": "NORMAL", "label": "宏观(旧SQLite)"},
    "global_macro": {"cache": -8000,   "mmap": 0,          "sync": "NORMAL", "label": "全球宏观(SQLite)"},
}

# 大表清单 — 这类表的无过滤 COUNT 需要 capped-count 优化
LARGE_TABLES = {"daily", "daily_basic", "moneyflow", "fina_indicator"}


# ── 连接管理 ──
_connections: dict[str, sqlite3.Connection] = {}
_conn_times: dict[str, float] = {}
_lock = threading.Lock()


def _is_pg(table: str) -> bool:
    """按表路由：表在 PG 中 → True；否则 SQLite"""
    return _PG_AVAILABLE and table in PG_TABLES


def _get_pg_conn():
    """新建 PG 连接（每次调用，用完即关；本地 PG 开销极小）"""
    return psycopg2.connect(**_PG_CONFIG)


def _get_conn(db_key: str) -> sqlite3.Connection:
    """获取 SQLite 数据库连接（按需创建，每个 DB 独立调优）"""
    now = time.time()

    # 已有连接：每 300s 健康检查
    if db_key in _connections:
        conn = _connections[db_key]
        elapsed = now - _conn_times.get(db_key, 0)
        if elapsed > 300:
            try:
                conn.execute("SELECT 1").fetchone()
                _conn_times[db_key] = now
                return conn
            except sqlite3.Error:
                _connections.pop(db_key, None)
                _conn_times.pop(db_key, None)

    with _lock:
        if db_key in _connections:
            return _connections[db_key]

        path = db_path(db_key)
        tune = DB_TUNE.get(db_key, {"cache": -8000, "mmap": 0, "sync": "NORMAL"})

        conn = sqlite3.connect(path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA synchronous={tune['sync']}")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute(f"PRAGMA cache_size={tune['cache']}")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA foreign_keys=OFF")
        if tune['mmap'] > 0:
            conn.execute(f"PRAGMA mmap_size={tune['mmap']}")
        conn.execute("PRAGMA page_size=4096")
        conn.execute("PRAGMA case_sensitive_like=OFF")
        conn.row_factory = sqlite3.Row

        _connections[db_key] = conn
        _conn_times[db_key] = now
        return conn


# ── DB KEY 映射 ──
TABLE_DB_MAP: dict[str, str] = {}
for db_key, tables in ALL_SCHEMAS.items():
    for table_name, _ in tables:
        TABLE_DB_MAP[table_name] = db_key
macro_tables = ["cpi", "ppi", "pmi", "gdp", "m2", "sf_month",
                "shibor", "shibor_lpr", "us_tycr",
                "cn_cpi", "cn_ppi", "cn_pmi", "cn_gdp", "cn_m"]
for t in macro_tables:
    TABLE_DB_MAP[t] = "macro"

# Global macro tables -> global_macro DB
for t in ["fred_series", "wb_data"]:
    TABLE_DB_MAP[t] = "global_macro"


def _quote(col: str) -> str:
    return f'"{col}"'


def _get_valid_cols(table: str) -> set[str]:
    """获取表字段集合（PG 用 pg_attribute，普通表+物化视图都覆盖；SQLite 用 PRAGMA）"""
    if _is_pg(table):
        conn = _get_pg_conn()
        try:
            df = pd.read_sql(
                "SELECT a.attname AS column_name FROM pg_class c "
                "JOIN pg_attribute a ON a.attrelid = c.oid "
                "WHERE c.relname = %s AND a.attnum > 0 AND NOT a.attisdropped",
                conn, params=[table],
            )
            return set(df["column_name"])
        finally:
            conn.close()
    db_key = TABLE_DB_MAP.get(table)
    if not db_key:
        return set()
    conn = _get_conn(db_key)
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return {r[1] for r in rows}


def _select_fields(fields: str, valid_cols: set) -> tuple[str, list[str]]:
    if not fields:
        return "*", []
    selected = []
    for f in fields.split(","):
        f = f.strip()
        if f in valid_cols:
            selected.append(_quote(f))
    if not selected:
        return "*", []
    return ", ".join(selected), [c.strip('"') for c in selected]


class SpDataService:
    """StockPulse 数据服务 — 市场数据的统一引擎（PG 优先 / SQLite 降级）"""

    @staticmethod
    def query(
        table: str,
        filters: dict = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: Optional[str] = None,
        sort_order: str = "desc",
        fields: Optional[str] = None,
        limit: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        date_col: str = "trade_date",
    ) -> StockPulseResponse:
        """通用数据查询（SQL 级分页，大表使用 capped-count）"""
        db_key = TABLE_DB_MAP.get(table)
        pg_mode = _is_pg(table)
        if not pg_mode and not db_key:
            return sp_error(SpError.NOT_FOUND, f"未知数据表: {table}")

        PH = "%s" if pg_mode else "?"

        try:
            conn = _get_pg_conn() if pg_mode else _get_conn(db_key)
            try:
                valid_cols = _get_valid_cols(table)
                if not valid_cols:
                    return sp_error(SpError.NOT_FOUND, f"数据表不存在: {table}")

                # ── 构建 WHERE ──
                where_clauses = []
                params: list = []

                if filters:
                    for col, val in filters.items():
                        col_clean = col.replace("__gte", "").replace("__lte", "")
                        if col_clean in valid_cols:
                            if col.endswith("__gte"):
                                where_clauses.append(f'{_quote(col_clean)}>={PH}')
                            elif col.endswith("__lte"):
                                where_clauses.append(f'{_quote(col_clean)}<={PH}')
                            else:
                                where_clauses.append(f'{_quote(col_clean)}={PH}')
                            params.append(val)

                # 日期范围
                if start_date:
                    if date_col in valid_cols:
                        where_clauses.append(f'{_quote(date_col)}>={PH}')
                        params.append(start_date.replace("-", ""))
                if end_date:
                    if date_col in valid_cols:
                        where_clauses.append(f'{_quote(date_col)}<={PH}')
                        params.append(end_date.replace("-", ""))

                where_str = ""
                if where_clauses:
                    where_str = " WHERE " + " AND ".join(where_clauses)

                # ── 排序 ──
                order_str = ""
                if sort_by and sort_by in valid_cols:
                    order_str = f' ORDER BY {_quote(sort_by)} {sort_order}'
                elif date_col in valid_cols:
                    order_str = f' ORDER BY {_quote(date_col)} DESC'

                # ── 字段选择 ──
                select_str, _ = _select_fields(fields, valid_cols)

                # ── LIMIT 模式（不计数，直接返回 N 行） ──
                if limit:
                    sql = f"SELECT {select_str} FROM {_quote(table)}{where_str}{order_str} LIMIT {PH}"
                    params.append(limit)
                    df = pd.read_sql(sql, conn, params=params)
                    return sp_success(
                        data=df.to_dict(orient="records") if not df.empty else []
                    )

                # ── 分页模式 ──
                # 大表无过滤条件时使用 capped-count 避免全表扫描
                has_where = bool(where_clauses)
                is_large = table in LARGE_TABLES

                if is_large and not has_where:
                    # capped-count: 只查 page_size*2+1 行，超过则标记 has_more
                    cap = page_size * 2 + 1
                    cap_sql = f"SELECT COUNT(*) as cnt FROM ({select_str} FROM {_quote(table)} LIMIT {PH}) AS sub"
                    cnt_df = pd.read_sql(cap_sql, conn, params=[(page + 1) * page_size])
                    actual = int(cnt_df.iloc[0]["cnt"]) if not cnt_df.empty else 0
                    capped = actual == (page + 1) * page_size  # 结果被截断，实际更大

                    total = actual if not capped else actual * 2  # 估算值
                    total_pages = max(1, (total + page_size - 1) // page_size)

                    # 实际数据查询
                    offset = (page - 1) * page_size
                    data_sql = (
                        f"SELECT {select_str} FROM {_quote(table)}{order_str} "
                        f"LIMIT {PH} OFFSET {PH}"
                    )
                    df = pd.read_sql(data_sql, conn, params=[page_size, offset])

                    return sp_success(
                        data=df.to_dict(orient="records") if not df.empty else [],
                        meta={
                            "total": total if not capped else f">{actual - page_size}",
                            "page": page,
                            "page_size": page_size,
                            "total_pages": total_pages if not capped else "?",
                            "has_next": capped or (page < total_pages and not df.empty),
                            "has_prev": page > 1,
                            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        }
                    )

                # ── 普通 COUNT（有过滤条件或小表） ──
                count_sql = f"SELECT COUNT(*) as cnt FROM {_quote(table)}{where_str}"
                cnt_df = pd.read_sql(count_sql, conn, params=params)
                total = int(cnt_df.iloc[0]["cnt"]) if not cnt_df.empty else 0

                if total == 0:
                    return sp_success(data=[], meta={
                        "total": 0, "page": page, "page_size": page_size,
                        "total_pages": 0, "has_next": False, "has_prev": False,
                    })

                total_pages = max(1, (total + page_size - 1) // page_size)
                offset = (page - 1) * page_size
                data_sql = (
                    f"SELECT {select_str} FROM {_quote(table)}{where_str}{order_str} "
                    f"LIMIT {PH} OFFSET {PH}"
                )
                data_params = params + [page_size, offset]
                df = pd.read_sql(data_sql, conn, params=data_params)

                return sp_success(
                    data=df.to_dict(orient="records") if not df.empty else [],
                    meta={
                        "total": total,
                        "page": page,
                        "page_size": page_size,
                        "total_pages": total_pages,
                        "has_next": page < total_pages,
                        "has_prev": page > 1,
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )
            finally:
                if pg_mode:
                    conn.close()
        except Exception as e:
            return sp_error(SpError.DB_ERROR, f"查询异常: {str(e)}")

    @staticmethod
    def query_raw(table: str, sql_str: str, params: list = None) -> pd.DataFrame:
        """直接执行原始 SQL（内部使用）— PG 模式自动将 ? 占位符转为 %s"""
        pg_mode = _is_pg(table)
        if pg_mode:
            conn = _get_pg_conn()
            try:
                pg_sql = sql_str.replace("?", "%s")
                return pd.read_sql(pg_sql, conn, params=params or [])
            finally:
                conn.close()
        db_key = TABLE_DB_MAP.get(table)
        if not db_key:
            return pd.DataFrame()
        conn = _get_conn(db_key)
        return pd.read_sql(sql_str, conn, params=params or [])

    @staticmethod
    def get_stock_name(ts_code: str) -> Optional[str]:
        """股票名称查询 — PG stock_basic（最新）"""
        if _PG_AVAILABLE:
            conn = _get_pg_conn()
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT name FROM stock_basic WHERE ts_code = %s",
                    (ts_code.upper(),),
                )
                row = cur.fetchone()
                return row[0] if row else None
            finally:
                conn.close()
        conn = _get_conn("master")
        cursor = conn.execute(
            "SELECT name FROM stock_basic WHERE ts_code=?",
            (ts_code.upper(),)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    @staticmethod
    def resolve_symbol(symbol: str) -> Optional[str]:
        """简码 -> ts_code 解析 — PG stock_basic（最新）"""
        if _PG_AVAILABLE:
            conn = _get_pg_conn()
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT ts_code FROM stock_basic WHERE symbol = %s",
                    (symbol,),
                )
                row = cur.fetchone()
                return row[0] if row else None
            finally:
                conn.close()
        conn = _get_conn("master")
        cursor = conn.execute(
            "SELECT ts_code FROM stock_basic WHERE symbol=?",
            (symbol,)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    @staticmethod
    def get_db_stats() -> dict:
        """获取各数据库连接状态（PG 优先 / SQLite 降级）"""
        stats = {}
        now = time.time()
        for db_key, cfg in DB_TUNE.items():
            age = None
            alive = False
            backend = "sqlite"
            retired = bool(cfg.get("retired"))
            err = None
            if retired:
                # 已退役库：不建连、不探测（避免 sqlite3.connect 凭空生成空库文件）
                pass
            elif db_key == "period" or db_key == "macro" or db_key == "global_macro":
                # SQLite 专属库：惰性连接，健康检查时主动探一次，反映真实可读性
                try:
                    path = db_path(db_key)
                    if not os.path.exists(path):
                        err = f"missing: {path}"
                    else:
                        conn = _connections.get(db_key) or _get_conn(db_key)
                        created = _conn_times.get(db_key)
                        if created:
                            age = int(now - created)
                        conn.execute("SELECT 1").fetchone()
                        alive = True
                except Exception as e:  # noqa: BLE001 — 健康检查不抛错，只降级记录
                    err = str(e)[:160]
            else:
                # PG 承载库
                if _PG_AVAILABLE:
                    backend = "postgresql"
                    try:
                        conn = _get_pg_conn()
                        try:
                            cur = conn.cursor()
                            cur.execute("SELECT 1")
                            cur.fetchone()
                            alive = True
                        finally:
                            conn.close()
                    except Exception:
                        alive = False
            stats[db_key] = {
                "label": cfg["label"],
                "backend": backend,
                "alive": alive,
                "retired": retired,
                "status": "retired" if retired else ("ok" if alive else "down"),
                **({"retired_note": cfg["retired_note"]} if retired and cfg.get("retired_note") else {}),
                **({"error": err} if err else {}),
                "cache_mb": abs(cfg["cache"]) // 1000,
                "mmap_gb": round(cfg["mmap"] / 1073741824, 1) if cfg["mmap"] > 0 else 0,
                "age_sec": age,
            }
        return stats
