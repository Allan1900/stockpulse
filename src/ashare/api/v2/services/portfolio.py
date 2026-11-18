"""组合管理服务 — Portfolio CRUD / NAV / 绩效统计 / Brinson 归因

2026-11-01 移植：由 dashboard/engine/portfolio.py 移植（保持逻辑等价），
读通道统一走 SpDataService.query_raw，写通道 psycopg2 直连（data_service 为纯读）。
供 REST /portfolio/* 端点与 MCP 工具复用。

数据表（PG ashare）：portfolio / portfolio_holding / portfolio_trade
"""
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import psycopg2
from datetime import datetime, timedelta

from ..data_service import SpDataService

_PG_CONFIG = {
    "host": "localhost",
    "dbname": "ashare",
    "user": "zrall",
    "options": "-c search_path=ashare,public",
}


def _get_conn():
    return psycopg2.connect(**_PG_CONFIG)


# ── 组合 CRUD ──────────────────────────────────────────

def list_portfolios():
    """列出所有组合"""
    return SpDataService.query_raw(
        "portfolio", "SELECT * FROM portfolio ORDER BY created_at DESC")


def create_portfolio(name, description=""):
    """创建新组合 → 返回 (pid, error?)"""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO portfolio (name, description) VALUES (%s, %s) RETURNING id",
            (name, description))
        pid = cur.fetchone()[0]
        conn.commit()
        return pid, None
    except Exception as e:
        conn.rollback()
        return None, str(e)
    finally:
        conn.close()


def delete_portfolio(pid):
    """删除组合（级联删除持仓）→ bool"""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM portfolio WHERE id=%s", (pid,))
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        conn.rollback()
        return False
    finally:
        conn.close()


def get_portfolio(pid):
    """组合基本信息 + 持仓列表（带股票名称/行业）→ (info_row_dict, holdings_df)"""
    info = SpDataService.query_raw(
        "portfolio", "SELECT * FROM portfolio WHERE id=%s", params=[pid])
    if info.empty:
        return None, None
    holdings = SpDataService.query_raw(
        "portfolio_holding",
        "SELECT h.*, s.name, s.industry FROM portfolio_holding h "
        "LEFT JOIN stock_basic s ON h.ts_code=s.ts_code "
        "WHERE h.portfolio_id=%s ORDER BY h.weight_pct DESC",
        params=[pid])
    return info.iloc[0], holdings


def add_holding(pid, ts_code, weight_pct, stop_price=None):
    """添加或更新持仓（UPSERT）→ (bool, error?)  可附带止损价 stop_price。"""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO portfolio_holding (portfolio_id, ts_code, weight_pct, stop_price) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (portfolio_id, ts_code) DO UPDATE "
            "  SET weight_pct=%s, stop_price=COALESCE(EXCLUDED.stop_price, portfolio_holding.stop_price)",
            (pid, ts_code, weight_pct, stop_price, weight_pct))
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def update_stop_price(pid, ts_code, stop_price):
    """更新持仓止损价 → bool。陈江挺'进场前确定止损位'落库。"""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE portfolio_holding SET stop_price=%s "
            "WHERE portfolio_id=%s AND ts_code=%s",
            (stop_price, pid, ts_code))
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        conn.rollback()
        return False
    finally:
        conn.close()


def remove_holding(pid, ts_code):
    """删除持仓 → bool"""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM portfolio_holding WHERE portfolio_id=%s AND ts_code=%s",
            (pid, ts_code))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ── 组合业绩计算 ──────────────────────────────────────

def calc_portfolio_nav(pid, start_date=None, end_date=None):
    """
    计算组合每日净值 (NAV) — 基准: 沪深300。
    返回 DataFrame: trade_date, nav, daily_return, bench_nav(可选), excess_return(可选)
    """
    info, holdings = get_portfolio(pid)
    if holdings is None or holdings.empty:
        return pd.DataFrame()

    codes = holdings["ts_code"].tolist()
    weights = holdings["weight_pct"].values / 100.0

    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
    # 归一化日期格式
    start_date = start_date.replace("-", "")
    end_date = end_date.replace("-", "")

    placeholders = ", ".join(["?"] * len(codes))
    df = SpDataService.query_raw(
        "daily",
        f"SELECT ts_code, trade_date, close, pct_chg FROM daily "
        f"WHERE ts_code IN ({placeholders}) AND trade_date>=? AND trade_date<=? "
        f"ORDER BY trade_date",
        params=codes + [start_date, end_date])
    if df.empty:
        return pd.DataFrame()

    returns_pivot = df.pivot_table(index="trade_date", columns="ts_code",
                                   values="pct_chg", aggfunc="first").fillna(0)

    common_codes = [c for c in codes if c in returns_pivot.columns]
    if not common_codes:
        return pd.DataFrame()
    valid_weights = np.array([weights[codes.index(c)] for c in common_codes])
    valid_weights = valid_weights / valid_weights.sum()

    portfolio_returns = returns_pivot[common_codes].dot(valid_weights) / 100.0
    nav = (1 + portfolio_returns).cumprod()
    nav = nav / nav.iloc[0]

    result = pd.DataFrame({
        "trade_date": nav.index,
        "nav": nav.values,
        "daily_return": portfolio_returns.values,
    }).reset_index(drop=True)

    bench = SpDataService.query_raw(
        "index_daily",
        "SELECT trade_date, pct_chg FROM index_daily "
        "WHERE ts_code='000300.SH' AND trade_date>=? AND trade_date<=? "
        "ORDER BY trade_date",
        params=[start_date, end_date])
    if not bench.empty:
        bench_nav = (1 + bench["pct_chg"] / 100.0).cumprod()
        bench_nav = bench_nav / bench_nav.iloc[0]
        bench_map = dict(zip(bench["trade_date"], bench_nav))
        result["bench_nav"] = result["trade_date"].map(bench_map)
        bench_daily = dict(zip(bench["trade_date"], bench["pct_chg"] / 100.0))
        result["excess_return"] = result["daily_return"] - result["trade_date"].map(bench_daily)
    return result


def calc_portfolio_stats(nav_df):
    """组合绩效统计：年化收益/波动/夏普/最大回撤/胜率 + 超额与信息比率"""
    if nav_df.empty:
        return {}
    n = len(nav_df)
    if n < 2:
        return {"error": "数据不足"}

    total_ret = float(nav_df["nav"].iloc[-1]) - 1
    years = n / 245

    ann_ret = (1 + total_ret) ** (1 / years) - 1 if years > 0 else 0
    ann_vol = float(nav_df["daily_return"].std()) * np.sqrt(245)
    sharpe = (ann_ret - 0.02) / ann_vol if ann_vol > 0 else 0

    peak = nav_df["nav"].cummax()
    drawdown = (nav_df["nav"] - peak) / peak
    max_dd = float(drawdown.min())

    win_rate = float((nav_df["daily_return"] > 0).mean())

    stats = {
        "total_return_pct": round(total_ret * 100, 2),
        "annual_return_pct": round(ann_ret * 100, 2),
        "annual_vol_pct": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "win_rate_pct": round(win_rate * 100, 1),
        "trading_days": n,
        "years": round(years, 1),
    }
    if "bench_nav" in nav_df.columns and "excess_return" in nav_df.columns:
        bench_total = float(nav_df["bench_nav"].iloc[-1])
        bench_ann = (bench_total) ** (1 / years) - 1 if years > 0 else 0
        tracking_error = float(nav_df["excess_return"].std()) * np.sqrt(245)
        ir = (ann_ret - bench_ann) / tracking_error if tracking_error > 0 else 0
        stats.update({
            "bench_total_return_pct": round((bench_total - 1) * 100, 2),
            "excess_return_pct": round((total_ret - (bench_total - 1)) * 100, 2),
            "information_ratio": round(ir, 2),
        })
    return stats


# ── Brinson 归因 ──────────────────────────────────────

def brinson_attribution(pid, start_date=None, end_date=None):
    """行业配置 × 个股选择 分解（简化版：以行业均值基准）"""
    info, holdings = get_portfolio(pid)
    if holdings is None or holdings.empty:
        return pd.DataFrame()

    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
    start_date = start_date.replace("-", "")
    end_date = end_date.replace("-", "")

    codes = holdings["ts_code"].tolist()
    placeholders = ", ".join(["?"] * len(codes))

    prices = SpDataService.query_raw(
        "daily",
        f"SELECT ts_code, trade_date, close FROM daily "
        f"WHERE ts_code IN ({placeholders}) AND trade_date>=? AND trade_date<=? "
        f"ORDER BY trade_date",
        params=codes + [start_date, end_date])
    if prices.empty:
        return pd.DataFrame()

    stocks = SpDataService.query_raw(
        "stock_basic", "SELECT ts_code, industry FROM stock_basic")
    ind_codes = stocks.groupby("industry")["ts_code"].apply(list).to_dict()

    # 各行业全市场等权收益（简化为各行业内部等权均值基准）
    ind_returns = {}
    for ind, ind_stocks in ind_codes.items():
        if not ind_stocks:
            continue
        ph2 = ", ".join(["?"] * len(ind_stocks))
        sub = SpDataService.query_raw(
            "daily",
            f"SELECT ts_code, trade_date, close FROM daily "
            f"WHERE ts_code IN ({ph2}) AND trade_date>=? AND trade_date<=? "
            f"ORDER BY trade_date",
            params=ind_stocks + [start_date, end_date])
        if not sub.empty and len(sub) >= 2:
            first_p = sub[sub["trade_date"] == sub["trade_date"].min()].set_index("ts_code")["close"]
            last_p = sub[sub["trade_date"] == sub["trade_date"].max()].set_index("ts_code")["close"]
            rets = (last_p / first_p - 1).mean()
            ind_returns[ind] = rets

    first_p = prices[prices["trade_date"] == prices["trade_date"].min()].set_index("ts_code")["close"]
    last_p = prices[prices["trade_date"] == prices["trade_date"].max()].set_index("ts_code")["close"]
    stock_rets = last_p / first_p - 1

    result_rows = []
    for _, row in holdings.iterrows():
        code = row["ts_code"]
        ind = row.get("industry", "")
        w = float(row["weight_pct"]) / 100.0
        stock_ret = float(stock_rets.get(code, 0))
        bench_ind_ret = ind_returns.get(ind, 0)
        selection = stock_ret - bench_ind_ret
        result_rows.append({
            "ts_code": code,
            "name": row.get("name", ""),
            "industry": ind,
            "weight_pct": round(w * 100, 1),
            "stock_return_pct": round(stock_ret * 100, 2),
            "industry_bench_pct": round(bench_ind_ret * 100, 2) if pd.notna(bench_ind_ret) else None,
            "selection_effect_pct": round(selection * 100, 2),
        })
    return pd.DataFrame(result_rows).sort_values("weight_pct", ascending=False)
