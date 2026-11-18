"""
数据浏览器引擎 — 对标 Wind EDB 数据浏览器

功能:
- 截面查询: 某一交易日全市场指定指标值
- 时序查询: 某股票指定指标的时间序列
- 全市场均值: 全市场某指标每日均值序列

指标分类:
- 行情类: close/open/high/low/pct_chg/vol/amount
- 估值类: pe/pe_ttm/pb/ps/ps_ttm/dv_ratio/dv_ttm
- 量能类: turnover_rate/turnover_rate_f/volume_ratio
- 市值类: total_mv/circ_mv/total_share/float_share/free_share
"""
import warnings
warnings.filterwarnings("ignore", message=".*SQLAlchemy connectable.*")

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from engine.query import sql as _sql

# ── 指标清单（分类 + 标签 + 格式化规则）───────────────

INDICATOR_GROUPS = {
    "行情指标": {
        "close":   {"label": "收盘价",     "format": "{:.2f}",       "unit": ""},
        "open":    {"label": "开盘价",     "format": "{:.2f}",       "unit": ""},
        "high":    {"label": "最高价",     "format": "{:.2f}",       "unit": ""},
        "low":     {"label": "最低价",     "format": "{:.2f}",       "unit": ""},
        "pct_chg": {"label": "涨跌幅",     "format": "{:.2f}%",      "unit": "%"},
        "vol":     {"label": "成交量",     "format": "{:.0f}",       "unit": "手"},
        "amount":  {"label": "成交额",     "format": "{:.2f}",       "unit": "亿元"},
    },
    "估值指标": {
        "pe":       {"label": "PE",         "format": "{:.2f}",       "unit": ""},
        "pe_ttm":   {"label": "PE-TTM",     "format": "{:.2f}",       "unit": ""},
        "pb":       {"label": "PB",         "format": "{:.2f}",       "unit": ""},
        "ps":       {"label": "PS",         "format": "{:.2f}",       "unit": ""},
        "ps_ttm":   {"label": "PS-TTM",     "format": "{:.2f}",       "unit": ""},
        "dv_ratio": {"label": "股息率",     "format": "{:.2f}%",      "unit": "%"},
        "dv_ttm":   {"label": "股息率TTM",   "format": "{:.2f}%",      "unit": "%"},
    },
    "量能指标": {
        "turnover_rate":   {"label": "换手率",     "format": "{:.2f}%",  "unit": "%"},
        "turnover_rate_f": {"label": "自由换手率",   "format": "{:.2f}%",  "unit": "%"},
        "volume_ratio":    {"label": "量比",       "format": "{:.2f}",    "unit": ""},
    },
    "市值指标": {
        "total_mv":    {"label": "总市值",   "format": "{:.2f}",  "unit": "亿元"},
        "circ_mv":     {"label": "流通市值", "format": "{:.2f}",  "unit": "亿元"},
        "total_share": {"label": "总股本",   "format": "{:.2f}",  "unit": "亿股"},
        "float_share": {"label": "流通股本", "format": "{:.2f}",  "unit": "亿股"},
        "free_share":  {"label": "自由流通股","format": "{:.2f}",  "unit": "亿股"},
    },
}


def get_indicator_list():
    """返回平坦的指标列表 [(code, label, group_name), ...]"""
    result = []
    for group, items in INDICATOR_GROUPS.items():
        for code, meta in items.items():
            result.append((code, meta["label"], group))
    return result


def _source_table(indicator):
    """判断指标来自 daily 还是 daily_basic"""
    daily_fields = {"close", "open", "high", "low", "pct_chg", "vol", "amount"}
    if indicator in daily_fields:
        return "daily"
    return "daily_basic"


def cross_section(trade_date, indicators, industry=None, top_n=None):
    """
    截面查询：指定交易日，所有股票的指定指标值

    返回: DataFrame (ts_code, name, industry, indicator1, indicator2, ...)
    """
    if isinstance(indicators, str):
        indicators = [indicators]

    # 按表分组查询
    tbl_daily = [i for i in indicators if _source_table(i) == "daily"]
    tbl_basic = [i for i in indicators if _source_table(i) == "daily_basic"]

    result = None

    if tbl_daily:
        fields = "ts_code, " + ", ".join(f'"{f}"' for f in tbl_daily)
        df_d = _sql(None,
                     f"SELECT {fields} FROM daily WHERE trade_date=%s",
                     params=[trade_date])
        if not df_d.empty:
            result = df_d

    if tbl_basic:
        fields = "ts_code, " + ", ".join(f'"{f}"' for f in tbl_basic)
        df_b = _sql(None,
                     f"SELECT {fields} FROM daily_basic WHERE trade_date=%s",
                     params=[trade_date])
        if not df_b.empty:
            if result is not None and not result.empty:
                result = result.merge(df_b, on="ts_code", how="outer")
            else:
                result = df_b

    if result is None or result.empty:
        return pd.DataFrame()

    # 关联股票基础信息
    stocks = _sql(None, "SELECT ts_code, name, industry FROM stock_basic")
    result = result.merge(stocks, on="ts_code", how="left")

    # 行业过滤
    if industry:
        if isinstance(industry, str):
            industry = [industry]
        result = result[result["industry"].isin(industry)]

    # TOP N 排序（按第一个指标降序）
    if top_n and len(indicators) > 0:
        result = result.sort_values(indicators[0], ascending=False).head(top_n)

    return result.reset_index(drop=True)


def time_series(stocks, indicators, start_date, end_date):
    """
    时序查询：选定股票 + 选定指标的时间序列

    返回: DataFrame (trade_date, ts_code1_ind1, ts_code1_ind2, ...)
    多股票多指标时返回宽表
    """
    if isinstance(stocks, str):
        stocks = [stocks]
    if isinstance(indicators, str):
        indicators = [indicators]

    # 按表分组
    tbl_daily = [i for i in indicators if _source_table(i) == "daily"]
    tbl_basic = [i for i in indicators if _source_table(i) == "daily_basic"]

    all_dfs = []

    for code in stocks:
        if tbl_daily:
            fields = "trade_date, " + ", ".join(f'"{f}"' for f in tbl_daily)
            df_d = _sql(None,
                         f"SELECT {fields} FROM daily WHERE ts_code=%s "
                         f"AND trade_date>=%s AND trade_date<=%s ORDER BY trade_date",
                         params=[code, start_date, end_date])
            if not df_d.empty:
                df_d = df_d.rename(columns={f: f"{code}_{f}" for f in tbl_daily})
                all_dfs.append(df_d)

        if tbl_basic:
            fields = "trade_date, " + ", ".join(f'"{f}"' for f in tbl_basic)
            df_b = _sql(None,
                         f"SELECT {fields} FROM daily_basic WHERE ts_code=%s "
                         f"AND trade_date>=%s AND trade_date<=%s ORDER BY trade_date",
                         params=[code, start_date, end_date])
            if not df_b.empty:
                df_b = df_b.rename(columns={f: f"{code}_{f}" for f in tbl_basic})
                all_dfs.append(df_b)

    if not all_dfs:
        return pd.DataFrame()

    # 按 trade_date 合并
    from functools import reduce
    merged = reduce(lambda left, right: pd.merge(left, right, on="trade_date", how="outer"),
                    all_dfs)
    return merged.sort_values("trade_date").reset_index(drop=True)


def market_average(indicator, start_date, end_date):
    """
    全市场均值时序：每日全市场某指标的均值/中位数

    返回: DataFrame (trade_date, mean, median, std, count, q25, q75)
    """
    tbl = _source_table(indicator)
    df = _sql(None,
              f"SELECT trade_date, {indicator} FROM {tbl} "
              f"WHERE trade_date>=%s AND trade_date<=%s "
              f"AND {indicator} IS NOT NULL AND {indicator} > 0 "
              f"ORDER BY trade_date",
              params=[start_date, end_date])

    if df.empty:
        return pd.DataFrame()

    stats = df.groupby("trade_date")[indicator].agg(
        ["mean", "median", "std", "count",
         lambda x: x.quantile(0.25),
         lambda x: x.quantile(0.75)]
    ).reset_index()
    stats.columns = ["trade_date", "mean", "median", "std", "count", "q25", "q75"]
    return stats.sort_values("trade_date").reset_index(drop=True)


def get_available_dates(table="daily_basic"):
    """获取有数据的日期列表（用于下拉选择）"""
    df = _sql(None,
              f"SELECT DISTINCT trade_date FROM {table} ORDER BY trade_date DESC LIMIT 500")
    return df["trade_date"].tolist() if not df.empty else []