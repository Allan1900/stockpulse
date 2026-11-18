"""
PostgreSQL 查询后端 — 与 engine/query.py API 完全兼容

所有函数签名与 SQLite 版一致，供 engine/query.py 在 PG 可用时自动选用。
db_key 参数保留以保持 API 兼容，实际被忽略（PG 所有表在同一 database）。
"""

import os
import warnings
from datetime import datetime, timedelta

import pandas as pd
import psycopg2

# pd.read_sql 直接使用 psycopg2 connection 完全正常
# 只是 pandas 没有正式测试过 DBAPI2 直连，warning 无实际影响
warnings.filterwarnings("ignore", message=".*SQLAlchemy connectable.*")

# ── 连接参数 ──────────────────────────────────────────
_PG_CONFIG = {
    "host": "localhost",
    "dbname": "ashare",
    "user": "zrall",
    "options": "-c search_path=ashare,public",
}

# pgpass 或 trust auth，无需密码


def _get_conn():
    """获取 PG 连接"""
    return psycopg2.connect(**_PG_CONFIG)


# ── 核心底层函数 ──────────────────────────────────────

def sql(db_key, query_str, params=None):
    """执行 SQL 查询，返回 DataFrame。db_key 保留兼容性，实际被忽略。

    在 PG 模式下 search_path=ashare,public，所以裸表名如 daily、
    weekly、stock_basic 会自动解析到 ashare  schema。
    """
    conn = _get_conn()
    try:
        return pd.read_sql(query_str, conn, params=params)
    finally:
        conn.close()


def sql_one(db_key, query_str, params=None):
    """执行 SQL 查询，返回单行 dict 或 None"""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(query_str, params or [])
        row = cur.fetchone()
        if row:
            return dict(zip([desc[0] for desc in cur.description], row))
        return None
    finally:
        conn.close()


def _today_str():
    return datetime.now().strftime("%Y%m%d")


def _six_months_ago():
    return (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")


# ── 股票基础信息 ──────────────────────────────────────

def get_stock_list():
    return sql(None,
               "SELECT ts_code, symbol, name, industry, area, market, list_date "
               "FROM stock_basic ORDER BY ts_code")


def get_industries():
    df = get_stock_list()
    return sorted(df["industry"].dropna().unique())


def get_trade_dates(start="20150101", end=None):
    if end is None:
        end = _today_str()
    df = sql(None,
             "SELECT cal_date FROM trade_cal WHERE is_open=1 "
             "AND cal_date>=%s AND cal_date<=%s ORDER BY cal_date",
             params=[start, end])
    return df["cal_date"].tolist() if not df.empty else []


def get_stock_names():
    df = get_stock_list()
    return dict(zip(df["ts_code"], df["name"]))


# ── 表结构查询 ────────────────────────────────────────

def get_tables_info():
    """查询 PG information_schema 获取表结构"""
    info = {}
    schema_tables = {
        "master":      ["stock_basic", "trade_cal", "index_basic"],
        "daily":       ["daily", "daily_basic"],
        "period":      ["weekly", "monthly"],
        "index":       ["index_daily"],
        "financial":   ["fina_indicator", "balancesheet", "cashflow", "income"],
        "moneyflow":   ["moneyflow"],
        "holders":     ["top10_holders", "stk_holdernumber"],
        "lhb":         ["top_list"],
        "macro":       ["macro_data", "macro_meta"],
    }
    conn = _get_conn()
    try:
        for db_key, tables in schema_tables.items():
            for table in tables:
                df_cols = pd.read_sql(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema='ashare' AND table_name=%s "
                    "ORDER BY ordinal_position",
                    conn, params=[table],
                )
                info[f"{db_key}.{table}"] = {
                    "db": db_key,
                    "table": table,
                    "columns": df_cols["column_name"].tolist(),
                    "col_count": len(df_cols),
                }
    finally:
        conn.close()
    return info


def search_fields(keyword):
    """模糊搜字段名"""
    df = sql(None,
             "SELECT table_name, column_name, data_type "
             "FROM information_schema.columns "
             "WHERE table_schema='ashare' AND LOWER(column_name) LIKE %s "
             "ORDER BY table_name, ordinal_position",
             params=[f"%{keyword.lower()}%"])
    if df.empty:
        return df
    results = []
    for _, row in df.iterrows():
        results.append({
            "字段": f"{row['table_name']}.{row['column_name']}",
            "表": row["table_name"],
            "列": row["column_name"],
        })
    return pd.DataFrame(results)


# ── 统一查询接口 ──────────────────────────────────────

def query(stocks=None, fields=None, start_date=None, end_date=None,
          industry=None, limit=None, order_by=None, freq="daily"):
    """
    统一查询接口 — PG 参数化版本

    所有值参数使用 %s 占位符和绑定变量，避免 SQL 注入和引号兼容问题。
    stock_basic 搜索路径自动解析到 ashare schema。
    """
    # 表映射 — 物化视图（weekly/monthly）已在 PG 中建好
    table_map = {
        "daily":   "daily",
        "weekly":  "weekly",
        "monthly": "monthly",
    }
    table = table_map.get(freq, "daily")

    # 解析字段
    if fields is None:
        fields = "ts_code,trade_date,close"
    if isinstance(fields, str):
        fields_list = [f.strip() for f in fields.split(",")]
    else:
        fields_list = list(fields)

    # 日期范围
    start = start_date.replace("-", "") if start_date else _six_months_ago()
    end = end_date.replace("-", "") if end_date else _today_str()

    # 构造 SELECT
    select_parts = []
    for f in fields_list:
        if "." in f:
            select_parts.append(f)
        else:
            select_parts.append(f'"{f}"')
    select_str = ", ".join(select_parts)

    # 构造 WHERE — 全部使用 %s 参数化
    params = []
    where_clauses = []

    where_clauses.append('"trade_date" >= %s')
    params.append(start)

    where_clauses.append('"trade_date" <= %s')
    params.append(end)

    if stocks:
        if isinstance(stocks, str):
            stocks = [s.strip() for s in stocks.split(",")]
        where_clauses.append('"ts_code" = ANY(%s)')
        params.append(stocks)

    if industry:
        where_clauses.append('"industry" = %s')
        params.append(industry)

    # 组装 SQL
    qstr = f"SELECT {select_str} FROM {table} WHERE {' AND '.join(where_clauses)}"
    if order_by:
        qstr += f" ORDER BY {order_by}"
    if limit:
        qstr += f" LIMIT {limit}"

    return sql(None, qstr, params)


# ── 个股查询 ──────────────────────────────────────────

def query_single_stock(ts_code, fields="*", start=None, end=None):
    sql_str = f"SELECT {fields} FROM daily WHERE ts_code=%s"
    params = [ts_code]
    if start:
        sql_str += " AND trade_date>=%s"; params.append(start.replace("-", ""))
    if end:
        sql_str += " AND trade_date<=%s"; params.append(end.replace("-", ""))
    sql_str += " ORDER BY trade_date"
    return sql(None, sql_str, params)


def get_daily_basic(ts_code, start=None, end=None):
    sql_str = "SELECT * FROM daily_basic WHERE ts_code=%s"
    params = [ts_code]
    if start:
        sql_str += " AND trade_date>=%s"; params.append(start.replace("-", ""))
    if end:
        sql_str += " AND trade_date<=%s"; params.append(end.replace("-", ""))
    sql_str += " ORDER BY trade_date"
    return sql(None, sql_str, params)


# ── 资金流 ────────────────────────────────────────────

def get_moneyflow(ts_code, start=None, end=None):
    sql_str = "SELECT * FROM moneyflow WHERE ts_code=%s"
    params = [ts_code]
    if start:
        sql_str += " AND trade_date>=%s"; params.append(start.replace("-", ""))
    if end:
        sql_str += " AND trade_date<=%s"; params.append(end.replace("-", ""))
    sql_str += " ORDER BY trade_date"
    return sql(None, sql_str, params)


def get_moneyflow_by_date(trade_date, sort_by="net_mf_amount",
                          direction="desc", top_n=20):
    dir_sql = "DESC" if direction == "desc" else "ASC"
    sql_str = (
        "SELECT ts_code, trade_date, net_mf_amount FROM moneyflow "
        "WHERE trade_date=%s ORDER BY net_mf_amount " + dir_sql + " LIMIT %s"
    )
    return sql(None, sql_str, params=[trade_date, top_n])


def get_moneyflow_dates():
    df = sql(None,
             "SELECT DISTINCT trade_date FROM moneyflow ORDER BY trade_date DESC")
    return df["trade_date"].tolist() if not df.empty else []


# ── 财务指标 ──────────────────────────────────────────

def get_financial(ts_code, start=None, end=None):
    sql_str = "SELECT * FROM fina_indicator WHERE ts_code=%s"
    params = [ts_code]
    if start:
        sql_str += " AND end_date>=%s"; params.append(start.replace("-", ""))
    if end:
        sql_str += " AND end_date<=%s"; params.append(end.replace("-", ""))
    sql_str += " ORDER BY end_date"
    return sql(None, sql_str, params)


def get_balancesheet(ts_code, start=None, end=None):
    sql_str = "SELECT * FROM balancesheet WHERE ts_code=%s"
    params = [ts_code]
    if start:
        sql_str += " AND end_date>=%s"; params.append(start.replace("-", ""))
    if end:
        sql_str += " AND end_date<=%s"; params.append(end.replace("-", ""))
    sql_str += " ORDER BY end_date"
    return sql(None, sql_str, params)


def get_cashflow(ts_code, start=None, end=None):
    sql_str = "SELECT * FROM cashflow WHERE ts_code=%s"
    params = [ts_code]
    if start:
        sql_str += " AND end_date>=%s"; params.append(start.replace("-", ""))
    if end:
        sql_str += " AND end_date<=%s"; params.append(end.replace("-", ""))
    sql_str += " ORDER BY end_date"
    return sql(None, sql_str, params)


# ── 股东数据 ──────────────────────────────────────────

def get_top10_holders(ts_code, start=None, end=None):
    sql_str = "SELECT * FROM top10_holders WHERE ts_code=%s"
    params = [ts_code]
    if start:
        sql_str += " AND end_date>=%s"; params.append(start.replace("-", ""))
    if end:
        sql_str += " AND end_date<=%s"; params.append(end.replace("-", ""))
    sql_str += " ORDER BY end_date"
    return sql(None, sql_str, params)


def get_stk_holdernumber(ts_code, start=None, end=None):
    sql_str = "SELECT * FROM stk_holdernumber WHERE ts_code=%s"
    params = [ts_code]
    if start:
        sql_str += " AND end_date>=%s"; params.append(start.replace("-", ""))
    if end:
        sql_str += " AND end_date<=%s"; params.append(end.replace("-", ""))
    sql_str += " ORDER BY end_date"
    return sql(None, sql_str, params)


# ── 龙虎榜 ────────────────────────────────────────────

def get_top_list_by_date(trade_date):
    return sql(None,
               "SELECT * FROM top_list WHERE trade_date=%s ORDER BY net_amount DESC",
               params=[trade_date])


def get_top_list_dates():
    df = sql(None,
             "SELECT DISTINCT trade_date FROM top_list ORDER BY trade_date DESC")
    return df["trade_date"].tolist() if not df.empty else []


# ── 行业分析 ──────────────────────────────────────────

def get_industry_performance(start=None, end=None, top_n=10):
    """计算行业涨跌幅排行 — 使用物化视图加速"""
    stocks = get_stock_list()
    if stocks.empty:
        return pd.DataFrame()
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
            results.append({
                "ts_code": code,
                "name": name_map.get(code, ""),
                "industry": ind,
                "return": ret,
            })

    result_df = pd.DataFrame(results)
    if result_df.empty:
        return result_df

    ind_perf = result_df.groupby("industry")["return"].agg(
        ["median", "mean", "std", "count"]
    )
    ind_perf = ind_perf.sort_values("median", ascending=False).head(top_n)
    ind_perf = ind_perf.reset_index()
    ind_perf.columns = ["行业", "涨幅中位数", "涨幅均值", "标准差", "股票数"]
    return ind_perf

# ── 宏观数据查询 ──────────────────────────────────────

def get_macro_data(indicator=None, metric=None, start=None, end=None, limit=500):
    """
    查询宏观数据（EAV 格式）
    
    Parameters
    ----------
    indicator : str or list, optional
        指标名，如 'cn_cpi', 'cn_ppi', 'shibor', 'shibor_lpr', 'us_tycr' 等
    metric : str, optional
        子指标过滤，如 'nt_yoy', '1y', 'on' 等
    start, end : str, optional
        日期范围 (YYYYMMDD 或 YYYYMM 格式)
    limit : int, default 500
        返回行数上限
    
    Returns
    -------
    pd.DataFrame
    """
    conn = _get_conn()
    if not conn:
        return pd.DataFrame()
    
    params = []
    where = []
    
    if indicator:
        if isinstance(indicator, list):
            where.append("indicator = ANY(%s)")
            params.append(indicator)
        else:
            where.append("indicator = %s")
            params.append(indicator)
    
    if metric:
        where.append("metric = %s")
        params.append(metric)
    
    if start:
        where.append("period >= %s")
        params.append(start)
    
    if end:
        where.append("period <= %s")
        params.append(end)
    
    where_clause = " AND ".join(where) if where else "TRUE"
    
    sql_str = f"""
        SELECT indicator, period, metric, value
        FROM ashare.macro_data
        WHERE {where_clause}
        ORDER BY indicator, period, metric
        LIMIT {limit}
    """
    
    try:
        df = pd.read_sql(sql_str, conn, params=params)
        return df
    except Exception as e:
        print(f"[pg_query] get_macro_data error: {e}")
        return pd.DataFrame()
    finally:
        conn.close()


def get_macro_indicators():
    """获取所有可用的宏观指标列表"""
    conn = _get_conn()
    if not conn:
        return []
    try:
        df = pd.read_sql(
            "SELECT DISTINCT indicator FROM ashare.macro_data ORDER BY indicator",
            conn
        )
        return df["indicator"].tolist()
    except Exception as e:
        print(f"[pg_query] get_macro_indicators error: {e}")
        return []
    finally:
        conn.close()


def get_macro_metrics(indicator):
    """获取指定指标的所有子指标列表"""
    conn = _get_conn()
    if not conn:
        return []
    try:
        df = pd.read_sql(
            "SELECT DISTINCT metric FROM ashare.macro_data WHERE indicator=%s ORDER BY metric",
            conn,
            params=[indicator]
        )
        return df["metric"].tolist()
    except Exception as e:
        print(f"[pg_query] get_macro_metrics error: {e}")
        return []
    finally:
        conn.close()


def get_macro_date_range(indicator):
    """获取指定指标的日期范围"""
    conn = _get_conn()
    if not conn:
        return (None, None)
    try:
        df = pd.read_sql(
            "SELECT MIN(period) as min_d, MAX(period) as max_d FROM ashare.macro_data WHERE indicator=%s",
            conn,
            params=[indicator]
        )
        if not df.empty:
            return (df.iloc[0]["min_d"], df.iloc[0]["max_d"])
        return (None, None)
    except:
        return (None, None)
    finally:
        conn.close()
