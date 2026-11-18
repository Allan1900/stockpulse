"""估值横截面引擎 — 对标 Bloomberg RV (Relative Value)

功能:
- 全市场估值分布 (PE/PB/PS)
- 行业估值水位 (历史分位数)
- 估值 × 涨幅散点分析
"""

import warnings
warnings.filterwarnings("ignore", message=".*SQLAlchemy connectable.*")

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from engine.query import sql as _sql


def get_valuation_snapshot(trade_date):
    """
    获取指定交易日全市场估值快照
    
    返回: DataFrame (ts_code, name, industry, pe, pe_ttm, pb, ps, 
                     ps_ttm, dv_ratio, total_mv, circ_mv, pct_chg)
    """
    df = _sql(None, """
        SELECT d.ts_code, s.name, s.industry,
               b.pe, b.pe_ttm, b.pb, b.ps, b.ps_ttm,
               b.dv_ratio, b.total_mv, b.circ_mv,
               d.pct_chg
        FROM daily_basic b
        JOIN stock_basic s ON b.ts_code = s.ts_code
        JOIN daily d ON b.ts_code = d.ts_code AND b.trade_date = d.trade_date
        WHERE b.trade_date = %s
        ORDER BY b.total_mv DESC
    """, params=[trade_date])

    return df


def industry_valuation_percentile(trade_date, lookback_years=5):
    """
    计算各行业当前估值在历史中的水位（分位数）
    
    返回: DataFrame (industry, pe_current, pe_median, pe_percentile,
                     pb_current, pb_median, pb_percentile)
    """
    # 当前估值
    current = _sql(None, """
        SELECT s.industry,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY b.pe_ttm) AS pe_median,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY b.pb) AS pb_median
        FROM daily_basic b
        JOIN stock_basic s ON b.ts_code = s.ts_code
        WHERE b.trade_date = %s AND b.pe_ttm > 0 AND b.pe_ttm < 500
              AND b.pb > 0 AND b.pb < 50
        GROUP BY s.industry
    """, params=[trade_date])

    if current.empty:
        return pd.DataFrame()

    # 历史数据 — 计算行业估值在过去 N 年的分位数
    start_date = (datetime.strptime(trade_date, "%Y%m%d") 
                  - timedelta(days=lookback_years * 365)).strftime("%Y%m%d")

    # 按月采样历史估值
    history = _sql(None, """
        SELECT s.industry, b.trade_date,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY b.pe_ttm) AS pe_median,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY b.pb) AS pb_median
        FROM daily_basic b
        JOIN stock_basic s ON b.ts_code = s.ts_code
        WHERE b.trade_date >= %s AND b.trade_date <= %s
              AND b.pe_ttm > 0 AND b.pe_ttm < 500
              AND b.pb > 0 AND b.pb < 50
              AND RIGHT(b.trade_date, 2) IN ('01', '15')
        GROUP BY s.industry, b.trade_date
        ORDER BY s.industry, b.trade_date
    """, params=[start_date, trade_date])

    if history.empty:
        return current

    # 对每个行业计算历史分位数
    results = []
    for _, cur_row in current.iterrows():
        ind = cur_row["industry"]
        ind_hist = history[history["industry"] == ind]

        if ind_hist.empty:
            results.append({
                "industry": ind,
                "pe_current": round(cur_row["pe_median"], 2),
                "pe_percentile": None,
                "pb_current": round(cur_row["pb_median"], 2),
                "pb_percentile": None,
            })
            continue

        pe_vals = ind_hist["pe_median"].dropna().values
        pb_vals = ind_hist["pb_median"].dropna().values

        pe_pctl = (pe_vals[pe_vals <= cur_row["pe_median"]].size / 
                   max(pe_vals.size, 1)) * 100 if pe_vals.size > 0 else None
        pb_pctl = (pb_vals[pb_vals <= cur_row["pb_median"]].size / 
                   max(pb_vals.size, 1)) * 100 if pb_vals.size > 0 else None

        results.append({
            "industry": ind,
            "pe_current": round(cur_row["pe_median"], 2),
            "pe_percentile": round(pe_pctl, 1) if pe_pctl is not None else None,
            "pb_current": round(cur_row["pb_median"], 2),
            "pb_percentile": round(pb_pctl, 1) if pb_pctl is not None else None,
        })

    return pd.DataFrame(results).sort_values("pe_percentile", ascending=False)


def get_available_valuation_dates():
    """获取有 daily_basic 数据的日期"""
    df = _sql(None, """
        SELECT DISTINCT trade_date FROM daily_basic 
        ORDER BY trade_date DESC LIMIT 500
    """)
    return df["trade_date"].tolist() if not df.empty else []