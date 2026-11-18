"""跨库查询引擎 — 线程安全版（适配 Streamlit 多线程）"""

import sqlite3, os
from datetime import datetime
from functools import lru_cache

import pandas as pd

from ..config import get_config, db_path


def _conn(db_key):
    """打开一个数据库连接（每次调用新建，线程安全）"""
    path = db_path(db_key)
    if not os.path.exists(path):
        return None
    return sqlite3.connect(path)


def sql(db_key, sql_str, params=None):
    """执行 SQL 查询，返回 DataFrame"""
    c = _conn(db_key)
    if c is None:
        return pd.DataFrame()
    try:
        return pd.read_sql(sql_str, c, params=params)
    finally:
        c.close()


def sql_one(db_key, sql_str, params=None):
    """执行 SQL 查询，返回单行"""
    c = _conn(db_key)
    if c is None:
        return None
    try:
        return c.execute(sql_str, params or []).fetchone()
    finally:
        c.close()


def get_stock_list():
    """完整股票列表"""
    return sql("master",
        "SELECT ts_code, symbol, name, industry, area, market, list_date "
        "FROM stock_basic ORDER BY ts_code")


def get_industries():
    """行业列表"""
    df = get_stock_list()
    return sorted(df["industry"].dropna().unique())


def get_trade_dates(start="20250101", end="20260619"):
    """交易日列表"""
    df = sql("master",
        "SELECT cal_date FROM trade_cal WHERE is_open=1 AND cal_date>=? AND cal_date<=? ORDER BY cal_date",
        params=[start, end])
    return df["cal_date"].tolist()


def get_stock_names():
    """ts_code -> name 映射"""
    df = get_stock_list()
    return dict(zip(df["ts_code"], df["name"]))


def get_tables_info():
    """所有表结构"""
    info = {}
    for key in ["master", "daily", "period", "index", "financial", "moneyflow",
                 "holders", "lhb", "macro"]:
        c = _conn(key)
        if c is None:
            continue
        tables = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' AND name!='meta'"
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
    """模糊搜字段"""
    results = []
    for key, tbl_info in get_tables_info().items():
        for col in tbl_info["columns"]:
            if keyword.lower() in col.lower():
                results.append({"field": f"{key}.{col}", "table": key, "column": col})
    return pd.DataFrame(results)


def query(stocks=None, fields=None, start_date=None, end_date=None,
          industry=None, limit=None, order_by=None, freq="daily"):
    """
    统一查询接口

    参数:
        stocks: str 或 list (ts_code)
        fields: str (逗号分隔) 或 list
        start_date/end_date: YYYYMMDD 或 YYYY-MM-DD
        freq: daily / weekly / monthly
    """
    freq_map = {
        "daily": ("daily", "daily"),
        "weekly": ("period", "weekly"),
        "monthly": ("period", "monthly"),
    }
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

    cfg = get_config()
    start = _norm(start_date) or cfg.default_start
    end = _norm(end_date) or datetime.now().strftime("%Y%m%d")

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

    select_str = ", ".join(select_parts)
    where_str = " AND ".join(where_parts)
    qstr = f'SELECT {select_str} FROM "{table}" WHERE {where_str}'

    if order_by:
        qstr += f" ORDER BY {order_by}"
    if limit:
        qstr += f" LIMIT {limit}"

    return sql(db_key, qstr)


def query_single_stock(ts_code, fields="*", start=None, end=None):
    """查询单只股票日线"""
    sql_str = f"SELECT {fields} FROM daily WHERE ts_code=? "
    params = [ts_code]
    if start:
        sql_str += "AND trade_date>=? "
        params.append(start.replace("-", ""))
    if end:
        sql_str += "AND trade_date<=? "
        params.append(end.replace("-", ""))
    sql_str += "ORDER BY trade_date"
    return sql("daily", sql_str, params)


def get_daily_basic(ts_code, start=None, end=None):
    """查询每日指标"""
    sql_str = "SELECT * FROM daily_basic WHERE ts_code=? "
    params = [ts_code]
    if start:
        sql_str += "AND trade_date>=? "
        params.append(start.replace("-", ""))
    if end:
        sql_str += "AND trade_date<=? "
        params.append(end.replace("-", ""))
    sql_str += "ORDER BY trade_date"
    return sql("daily", sql_str, params)


def get_moneyflow(ts_code, start=None, end=None):
    """查询个股资金流"""
    sql_str = "SELECT * FROM moneyflow WHERE ts_code=? "
    params = [ts_code]
    if start:
        sql_str += "AND trade_date>=? "
        params.append(start.replace("-", ""))
    if end:
        sql_str += "AND trade_date<=? "
        params.append(end.replace("-", ""))
    sql_str += "ORDER BY trade_date"
    return sql("moneyflow", sql_str, params)


def get_moneyflow_by_date(trade_date, sort_by="net_mf_amount",
                          direction="desc", top_n=20):
    """按日期获取全市场资金排行"""
    dir_sql = "DESC" if direction == "desc" else "ASC"
    sql_str = (f"SELECT ts_code, trade_date, {sort_by} FROM moneyflow "
               f"WHERE trade_date=? ORDER BY {sort_by} {dir_sql} LIMIT ?")
    return sql("moneyflow", sql_str, params=[trade_date, top_n])


def get_moneyflow_dates():
    """获取有资金流数据的日期"""
    df = sql("moneyflow",
             "SELECT DISTINCT trade_date FROM moneyflow ORDER BY trade_date DESC")
    return df["trade_date"].tolist() if not df.empty else []


def get_financial(ts_code, start=None, end=None):
    """查询财务指标"""
    sql_str = "SELECT * FROM fina_indicator WHERE ts_code=? "
    params = [ts_code]
    if start:
        sql_str += "AND end_date>=? "
        params.append(start.replace("-", ""))
    if end:
        sql_str += "AND end_date<=? "
        params.append(end.replace("-", ""))
    sql_str += "ORDER BY end_date"
    return sql("financial", sql_str, params)


def get_balancesheet(ts_code, start=None, end=None):
    """查询资产负债表"""
    sql_str = "SELECT * FROM balancesheet WHERE ts_code=? "
    params = [ts_code]
    if start:
        sql_str += "AND end_date>=? "
        params.append(start.replace("-", ""))
    if end:
        sql_str += "AND end_date<=? "
        params.append(end.replace("-", ""))
    sql_str += "ORDER BY end_date"
    return sql("financial", sql_str, params)


def get_cashflow(ts_code, start=None, end=None):
    """查询现金流量表"""
    sql_str = "SELECT * FROM cashflow WHERE ts_code=? "
    params = [ts_code]
    if start:
        sql_str += "AND end_date>=? "
        params.append(start.replace("-", ""))
    if end:
        sql_str += "AND end_date<=? "
        params.append(end.replace("-", ""))
    sql_str += "ORDER BY end_date"
    return sql("financial", sql_str, params)


def get_income(ts_code, start=None, end=None):
    """查询利润表"""
    sql_str = "SELECT * FROM income WHERE ts_code=? "
    params = [ts_code]
    if start:
        sql_str += "AND end_date>=? "
        params.append(start.replace("-", ""))
    if end:
        sql_str += "AND end_date<=? "
        params.append(end.replace("-", ""))
    sql_str += "ORDER BY end_date"
    return sql("financial", sql_str, params)


def get_top10_holders(ts_code, start=None, end=None):
    """查询前十大股东"""
    sql_str = "SELECT * FROM top10_holders WHERE ts_code=? "
    params = [ts_code]
    if start:
        sql_str += "AND end_date>=? "
        params.append(start.replace("-", ""))
    if end:
        sql_str += "AND end_date<=? "
        params.append(end.replace("-", ""))
    sql_str += "ORDER BY end_date"
    return sql("holders", sql_str, params)


def get_stk_holdernumber(ts_code, start=None, end=None):
    """查询股东人数"""
    sql_str = "SELECT * FROM stk_holdernumber WHERE ts_code=? "
    params = [ts_code]
    if start:
        sql_str += "AND end_date>=? "
        params.append(start.replace("-", ""))
    if end:
        sql_str += "AND end_date<=? "
        params.append(end.replace("-", ""))
    sql_str += "ORDER BY end_date"
    return sql("holders", sql_str, params)


def get_top_list_by_date(trade_date):
    """查询某日龙虎榜"""
    return sql("lhb",
        "SELECT * FROM top_list WHERE trade_date=? ORDER BY net_amount DESC",
        params=[trade_date])


def get_top_list_dates():
    """获取龙虎榜有数据的日期"""
    df = sql("lhb",
        "SELECT DISTINCT trade_date FROM top_list ORDER BY trade_date DESC")
    return df["trade_date"].tolist() if not df.empty else []


def get_index_daily(index_code="000001.SH", start=None, end=None):
    """查询指数日线"""
    sql_str = "SELECT * FROM index_daily WHERE ts_code=? "
    params = [index_code]
    if start:
        sql_str += "AND trade_date>=? "
        params.append(start.replace("-", ""))
    if end:
        sql_str += "AND trade_date<=? "
        params.append(end.replace("-", ""))
    sql_str += "ORDER BY trade_date"
    return sql("index", sql_str, params)


def get_macro(macro_table, start=None, end=None):
    """查询宏观经济数据"""
    sql_str = f"SELECT * FROM {macro_table} WHERE 1=1 "
    params = []
    if start:
        sql_str += "AND date>=? "
        params.append(start.replace("-", ""))
    if end:
        sql_str += "AND date<=? "
        params.append(end.replace("-", ""))
    sql_str += "ORDER BY date"
    return sql("macro", sql_str, params)


def get_industry_performance(start=None, end=None, top_n=10):
    """计算行业涨跌幅排行"""
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
            results.append({
                "ts_code": code, "name": name_map.get(code, ""),
                "industry": ind, "return": ret,
            })

    result_df = pd.DataFrame(results)
    if result_df.empty:
        return result_df

    ind_perf = result_df.groupby("industry")["return"].agg(
        ["median", "mean", "std", "count"])
    ind_perf = ind_perf.sort_values("median", ascending=False).head(top_n)
    ind_perf = ind_perf.reset_index()
    ind_perf.columns = ["industry", "median_return", "mean_return", "std", "stock_count"]
    return ind_perf


def run_query(ts_code, days, start, end, fields, csv_mode, limit):
    """CLI 查询入口"""
    if ts_code is None:
        df = get_stock_list()
        print(f"全部股票: {len(df)} 只")
        print(df[["ts_code", "name", "industry", "market"]].to_string(index=False))
        return

    # 计算时间范围
    if days:
        trade_dates = get_trade_dates()
        if len(trade_dates) >= days:
            end = trade_dates[-1]
            start = trade_dates[-days]
        else:
            start = trade_dates[0]
            end = trade_dates[-1]

    df = query_single_stock(ts_code, fields, start, end)

    if df.empty:
        print(f"无数据: {ts_code}")
        return

    if csv_mode:
        print(df.to_csv(index=False))
    else:
        name_map = get_stock_names()
        name = name_map.get(ts_code, ts_code)
        print(f"{name} ({ts_code}) — {len(df)} 条记录")
        print(f"日期范围: {df['trade_date'].iloc[0]} ~ {df['trade_date'].iloc[-1]}")
        print()

        # 展示最后几行
        show = df.tail(limit)
        pd.set_option("display.max_columns", 20)
        pd.set_option("display.width", 200)
        print(show.to_string(index=False))