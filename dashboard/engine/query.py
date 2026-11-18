"""
统一查询引擎 — PG 自动探测 → SQLite 降级

在启动时探测 PostgreSQL 是否可用：
  1. PostgreSQL 可用 → 从 engine.pg_query 导入所有函数
  2. PostgreSQL 不可用 → 降级到内置 SQLite 后端

所有页面无需改动，import 方式不变。
"""

import os as _os
_DASH = _os.environ.get("SP_DASHBOARD_DIR") or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_ENGINE = _os.environ.get("SP_ENGINE_DIR") or _os.path.dirname(_os.path.abspath(__file__))
_DATA = _os.environ.get("SP_DATA_DIR") or _os.path.join(_os.path.expanduser("~"), "ashare_data")
import os
from datetime import datetime

import pandas as pd

# ═══════════════════════════════════════════════════════
# PG 可用性探测
# ═══════════════════════════════════════════════════════

_PG_AVAILABLE = False
try:
    import psycopg2
    _test = psycopg2.connect(
        host="localhost", dbname="ashare", user="zrall",
        options="-c search_path=ashare,public",
    )
    _test.close()
    _PG_AVAILABLE = True
except Exception:
    pass

if _PG_AVAILABLE:
    # ── 全部委托给 PG 后端 ──────────────────────────
    from engine.pg_query import (
        sql, sql_one,
        get_stock_list, get_industries, get_trade_dates, get_stock_names,
        get_tables_info, search_fields,
        query, query_single_stock, get_daily_basic,
        get_moneyflow, get_moneyflow_by_date, get_moneyflow_dates,
        get_financial, get_balancesheet, get_cashflow,
        get_top10_holders, get_stk_holdernumber,
        get_top_list_by_date, get_top_list_dates,
        get_industry_performance,
    )
    _BACKEND = "postgresql"
    _BACKEND_LABEL = "🐘 PostgreSQL (ashare)"

    # ── 混合路由 (交易时段→实时, 盘后→PG) ──────────
    def hybrid_stock_quote(ts_code: str) -> dict:
        """智能混合查询: 交易时段走实时API, 盘后走PG"""
        try:
            from engine.realtime import hybrid_quote
            return hybrid_quote(ts_code)
        except Exception:
            # fallback: 走 PG
            row = sql_one(
                None,
                "SELECT trade_date, close, pct_chg, open, high, low FROM daily "
                "WHERE ts_code=%s ORDER BY trade_date DESC LIMIT 1",
                [ts_code],
            )
            if row:
                return {
                    "ts_code": ts_code,
                    "price": float(row["close"]),
                    "pct_chg": float(row["pct_chg"]),
                    "trade_date": str(row["trade_date"]),
                    "source": "pg_fallback",
                }
            return {"error": f"无数据: {ts_code}"}

    def is_trading_session() -> bool:
        """判断当前是否 A 股交易时段"""
        try:
            from engine.realtime import is_trading_time
            return is_trading_time()
        except Exception:
            return False
else:
    # ── SQLite 降级后端 ──────────────────────────────
    _BACKEND = "sqlite"
    _BACKEND_LABEL = "🗄️ SQLite (降级)"

    import sqlite3
    from functools import lru_cache

    DB_DIR = _DATA

    def _conn(db_key):
        """打开 SQLite 数据库连接"""
        path = {
            "master":    "ashare_master.db",
            "daily":     "ashare_daily.db",
            "period":    "ashare_period.db",
            "index":     "ashare_index.db",
            "financial": "ashare_financial.db",
            "moneyflow": "ashare_moneyflow.db",
            "holders":   "ashare_holders.db",
            "lhb":       "ashare_lhb.db",
        }[db_key]
        full = os.path.join(DB_DIR, path)
        if not os.path.exists(full):
            return None
        return sqlite3.connect(full)

    def sql(db_key, query_str, params=None):
        c = _conn(db_key)
        if c is None:
            return pd.DataFrame()
        try:
            return pd.read_sql(query_str, c, params=params)
        finally:
            c.close()

    def sql_one(db_key, query_str, params=None):
        c = _conn(db_key)
        if c is None:
            return None
        try:
            return c.execute(query_str, params or []).fetchone()
        finally:
            c.close()

    def get_stock_list():
        return sql("master",
                   "SELECT ts_code, symbol, name, industry, area, market, list_date FROM stock_basic ORDER BY ts_code")

    def get_industries():
        df = get_stock_list()
        return sorted(df["industry"].dropna().unique())

    def get_trade_dates(start="20150101", end=None):
        if end is None:
            end = datetime.now().strftime("%Y%m%d")
        df = sql("master",
                 "SELECT cal_date FROM trade_cal WHERE is_open=1 AND cal_date>=? AND cal_date<=? ORDER BY cal_date",
                 params=[start, end])
        return df["cal_date"].tolist()

    def get_stock_names():
        df = get_stock_list()
        return dict(zip(df["ts_code"], df["name"]))

    def get_tables_info():
        info = {}
        for key in ["master", "daily", "period", "index", "financial", "moneyflow", "holders", "lhb"]:
            c = _conn(key)
            if c is None:
                continue
            tables = c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='meta'"
            ).fetchall()
            for (t,) in tables:
                cols = c.execute(f'PRAGMA table_info("{t}")').fetchall()
                info[f"{key}.{t}"] = {
                    "db": key,
                    "table": t,
                    "columns": [c[1] for c in cols],
                    "col_count": len(cols),
                }
            c.close()
        return info

    def search_fields(keyword):
        results = []
        for key, info in get_tables_info().items():
            for col in info["columns"]:
                if keyword.lower() in col.lower():
                    results.append({"字段": f"{key}.{col}", "表": key, "列": col})
        return pd.DataFrame(results)

    def query(stocks=None, fields=None, start_date=None, end_date=None,
              industry=None, limit=None, order_by=None, freq="daily"):
        freq_map = {"daily": ("daily", "daily"), "weekly": ("period", "weekly"), "monthly": ("period", "monthly")}
        if freq not in freq_map:
            raise ValueError(f"不支持频率: {freq}")
        db_key, table = freq_map[freq]

        if fields is None:
            fields = "ts_code,trade_date,close"
        if isinstance(fields, str):
            fields_list = [f.strip() for f in fields.split(",")]
        else:
            fields_list = list(fields)

        def _norm(d):
            if d is None:
                return None
            return d.replace("-", "")
        start = _norm(start_date)
        end = _norm(end_date)

        select_parts = []
        for f in fields_list:
            if "." in f:
                select_parts.append(f)
            else:
                select_parts.append(f'"{f}"')

        where_parts = [f'"trade_date" >= "{start}"', f'"trade_date" <= "{end}"']

        if stocks:
            if isinstance(stocks, str):
                stocks = [s.strip() for s in stocks.split(",")]
            codes_str = ",".join([f'"{s}"' for s in stocks])
            where_parts.append(f'"ts_code" IN ({codes_str})')

        if industry:
            where_parts.append(f'"industry" = "{industry}"')

        select_str = ", ".join(select_parts)
        where_str = " AND ".join(where_parts)
        qstr = f'SELECT {select_str} FROM "{table}" WHERE {where_str}'

        if order_by:
            qstr += f" ORDER BY {order_by}"
        if limit:
            qstr += f" LIMIT {limit}"

        return sql(db_key, qstr)

    def query_single_stock(ts_code, fields="*", start=None, end=None):
        sql_str = f"SELECT {fields} FROM daily WHERE ts_code=? "
        params = [ts_code]
        if start:
            sql_str += "AND trade_date>=? "; params.append(start.replace("-", ""))
        if end:
            sql_str += "AND trade_date<=? "; params.append(end.replace("-", ""))
        sql_str += "ORDER BY trade_date"
        return sql("daily", sql_str, params)

    def get_daily_basic(ts_code, start=None, end=None):
        sql_str = "SELECT * FROM daily_basic WHERE ts_code=? "
        params = [ts_code]
        if start:
            sql_str += "AND trade_date>=? "; params.append(start.replace("-", ""))
        if end:
            sql_str += "AND trade_date<=? "; params.append(end.replace("-", ""))
        sql_str += "ORDER BY trade_date"
        return sql("daily", sql_str, params)

    def get_moneyflow(ts_code, start=None, end=None):
        sql_str = "SELECT * FROM moneyflow WHERE ts_code=? "
        params = [ts_code]
        if start:
            sql_str += "AND trade_date>=? "; params.append(start.replace("-", ""))
        if end:
            sql_str += "AND trade_date<=? "; params.append(end.replace("-", ""))
        sql_str += "ORDER BY trade_date"
        return sql("moneyflow", sql_str, params)

    def get_moneyflow_by_date(trade_date, sort_by="net_mf_amount", direction="desc", top_n=20):
        dir_sql = "DESC" if direction == "desc" else "ASC"
        sql_str = f"SELECT ts_code, trade_date, net_mf_amount FROM moneyflow WHERE trade_date=? ORDER BY net_mf_amount {dir_sql} LIMIT ?"
        return sql("moneyflow", sql_str, params=[trade_date, top_n])

    def get_moneyflow_dates():
        df = sql("moneyflow", "SELECT DISTINCT trade_date FROM moneyflow ORDER BY trade_date DESC")
        return df["trade_date"].tolist() if not df.empty else []

    def get_financial(ts_code, start=None, end=None):
        sql_str = "SELECT * FROM fina_indicator WHERE ts_code=? "
        params = [ts_code]
        if start:
            sql_str += "AND end_date>=? "; params.append(start.replace("-", ""))
        if end:
            sql_str += "AND end_date<=? "; params.append(end.replace("-", ""))
        sql_str += "ORDER BY end_date"
        return sql("financial", sql_str, params)

    def get_balancesheet(ts_code, start=None, end=None):
        sql_str = "SELECT * FROM balancesheet WHERE ts_code=? "
        params = [ts_code]
        if start:
            sql_str += "AND end_date>=? "; params.append(start.replace("-", ""))
        if end:
            sql_str += "AND end_date<=? "; params.append(end.replace("-", ""))
        sql_str += "ORDER BY end_date"
        return sql("financial", sql_str, params)

    def get_cashflow(ts_code, start=None, end=None):
        sql_str = "SELECT * FROM cashflow WHERE ts_code=? "
        params = [ts_code]
        if start:
            sql_str += "AND end_date>=? "; params.append(start.replace("-", ""))
        if end:
            sql_str += "AND end_date<=? "; params.append(end.replace("-", ""))
        sql_str += "ORDER BY end_date"
        return sql("financial", sql_str, params)

    def get_top10_holders(ts_code, start=None, end=None):
        sql_str = "SELECT * FROM top10_holders WHERE ts_code=? "
        params = [ts_code]
        if start:
            sql_str += "AND end_date>=? "; params.append(start.replace("-", ""))
        if end:
            sql_str += "AND end_date<=? "; params.append(end.replace("-", ""))
        sql_str += "ORDER BY end_date"
        return sql("holders", sql_str, params)

    def get_stk_holdernumber(ts_code, start=None, end=None):
        sql_str = "SELECT * FROM stk_holdernumber WHERE ts_code=? "
        params = [ts_code]
        if start:
            sql_str += "AND end_date>=? "; params.append(start.replace("-", ""))
        if end:
            sql_str += "AND end_date<=? "; params.append(end.replace("-", ""))
        sql_str += "ORDER BY end_date"
        return sql("holders", sql_str, params)

    def get_top_list_by_date(trade_date):
        return sql("lhb",
                   "SELECT * FROM top_list WHERE trade_date=? ORDER BY net_amount DESC",
                   params=[trade_date])

    def get_top_list_dates():
        df = sql("lhb", "SELECT DISTINCT trade_date FROM top_list ORDER BY trade_date DESC")
        return df["trade_date"].tolist() if not df.empty else []

    def get_industry_performance(start=None, end=None, top_n=10):
        stocks = get_stock_list()
        df = query(fields="ts_code,close", start_date=start, end_date=end)
        if df.empty:
            return pd.DataFrame()

        first_close = df.groupby("ts_code").first()["close"]
        last_close = df.groupby("ts_code").last()["close"]
        returns = ((last_close / first_close) - 1) * 100

        ind_map = dict(zip(stocks["ts_code"], stocks["industry"]))
        name_map = dict(zip(stocks["ts_code"], stocks["name"]))

        results = []
        for code, ret in returns.items():
            ind = ind_map.get(code)
            if ind:
                results.append({"ts_code": code, "name": name_map.get(code, ""), "industry": ind, "return": ret})

        result_df = pd.DataFrame(results)
        if result_df.empty:
            return result_df

        ind_perf = result_df.groupby("industry")["return"].agg(["median", "mean", "std", "count"])
        ind_perf = ind_perf.sort_values("median", ascending=False).head(top_n)
        ind_perf = ind_perf.reset_index()
        ind_perf.columns = ["行业", "涨幅中位数", "涨幅均值", "标准差", "股票数"]
        return ind_perf


# ═══════════════════════════════════════════════════════
# 导出通用工具
# ═══════════════════════════════════════════════════════

def get_backend():
    """返回当前后端类型: 'postgresql' 或 'sqlite'"""
    return _BACKEND


def get_backend_label():
    """返回可读的后端标签"""
    return _BACKEND_LABEL


def get_pg_stats():
    """查询 PG 统计信息（仅 PG 模式有效）"""
    if not _PG_AVAILABLE:
        return {}
    from engine.pg_query import _get_conn
    conn = _get_conn()
    try:
        cur = conn.cursor()

        # 行数
        cur.execute("""
            SELECT relname, n_live_tup, pg_size_pretty(pg_total_relation_size(relid))
            FROM pg_stat_user_tables
            WHERE schemaname='ashare'
            ORDER BY n_live_tup DESC
            LIMIT 10
        """)
        rows = [{"table": r[0], "rows": r[1], "size": r[2]} for r in cur.fetchall()]

        # 数据库大小
        cur.execute("SELECT pg_size_pretty(pg_database_size('ashare'))")
        db_size = cur.fetchone()[0]

        # PG 版本
        cur.execute("SELECT version()")
        version = cur.fetchone()[0].split(",")[0]

        return {"rows": rows, "db_size": db_size, "version": version}
    finally:
        conn.close()