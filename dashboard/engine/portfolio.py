"""
组合管理引擎 — Portfolio 创建/持仓/净值/归因分析

对标 Bloomberg PORT / FactSet Portfolio Analytics
"""
import warnings
warnings.filterwarnings("ignore", message=".*SQLAlchemy connectable.*")

import pandas as pd
import numpy as np
import psycopg2
from datetime import datetime, timedelta

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
    conn = _get_conn()
    try:
        df = pd.read_sql("SELECT * FROM portfolio ORDER BY created_at DESC", conn)
        return df
    finally:
        conn.close()


def create_portfolio(name, description=""):
    """创建新组合"""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO portfolio (name, description) VALUES (%s, %s) RETURNING id",
            (name, description),
        )
        pid = cur.fetchone()[0]
        conn.commit()
        return pid
    finally:
        conn.close()


def delete_portfolio(pid):
    """删除组合（级联删除持仓）"""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM portfolio WHERE id=%s", (pid,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_portfolio(pid):
    """获取组合基本信息 + 持仓列表"""
    conn = _get_conn()
    try:
        info = pd.read_sql("SELECT * FROM portfolio WHERE id=%s", conn, params=[pid])
        if info.empty:
            return None, None
        holdings = pd.read_sql(
            "SELECT h.*, s.name, s.industry FROM portfolio_holding h "
            "LEFT JOIN stock_basic s ON h.ts_code=s.ts_code "
            "WHERE h.portfolio_id=%s ORDER BY h.weight_pct DESC",
            conn, params=[pid],
        )
        return info.iloc[0], holdings
    finally:
        conn.close()


def add_holding(pid, ts_code, weight_pct):
    """添加或更新持仓"""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        # 使用 UPSERT — 若已存在则更新权重
        cur.execute(
            "INSERT INTO portfolio_holding (portfolio_id, ts_code, weight_pct) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (portfolio_id, ts_code) DO UPDATE SET weight_pct=%s",
            (pid, ts_code, weight_pct, weight_pct),
        )
        conn.commit()
        return True
    except Exception as e:
        return str(e)
    finally:
        conn.close()


def remove_holding(pid, ts_code):
    """删除持仓"""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM portfolio_holding WHERE portfolio_id=%s AND ts_code=%s",
            (pid, ts_code),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ── 组合业绩计算 ──────────────────────────────────────

PERF_FIELDS = "ts_code,trade_date,close,pct_chg"


def calc_portfolio_nav(pid, start_date=None, end_date=None):
    """
    计算组合每日净值 (NAV)
    
    返回 DataFrame: trade_date, nav, daily_return, cumulative_return
    基准: 沪深300 同期表现
    """
    info, holdings = get_portfolio(pid)
    if holdings is None or holdings.empty:
        return pd.DataFrame()

    codes = holdings["ts_code"].tolist()
    weights = holdings["weight_pct"].values / 100.0  # 转小数

    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")

    # 批量拉取行情数据
    from engine.query import sql

    placeholders = ", ".join(["%s"] * len(codes))
    df = sql(
        None,
        f"SELECT ts_code, trade_date, close, pct_chg FROM daily "
        f"WHERE ts_code IN ({placeholders}) AND trade_date>=%s AND trade_date<=%s "
        f"ORDER BY trade_date",
        params=codes + [start_date, end_date],
    )
    if df.empty:
        return pd.DataFrame()

    # 构建个股收益率矩阵
    returns_pivot = df.pivot_table(index="trade_date", columns="ts_code",
                                   values="pct_chg", aggfunc="first")
    # 填充缺失值（停牌日使用 0 收益）
    returns_pivot = returns_pivot.fillna(0)

    # 组合日收益率 = 加权平均
    common_codes = [c for c in codes if c in returns_pivot.columns]
    valid_weights = np.array([weights[codes.index(c)] for c in common_codes])
    valid_weights = valid_weights / valid_weights.sum()  # 重归一化

    portfolio_returns = returns_pivot[common_codes].dot(valid_weights) / 100.0

    # NAV 序列（基日 = 1.0）
    nav = (1 + portfolio_returns).cumprod()
    first_nav = nav.iloc[0]
    nav = nav / first_nav  # 归一化到 1.0

    result = pd.DataFrame({
        "trade_date": nav.index,
        "nav": nav.values,
        "daily_return": portfolio_returns.values,
    })
    result = result.reset_index(drop=True)

    # 沪深300 基准
    bench = sql(
        None,
        "SELECT trade_date, pct_chg FROM index_daily "
        "WHERE ts_code='000300.SH' AND trade_date>=%s AND trade_date<=%s "
        "ORDER BY trade_date",
        params=[start_date, end_date],
    )
    if not bench.empty:
        bench_ret = bench["pct_chg"] / 100.0
        bench_nav = (1 + bench_ret).cumprod()
        bench_nav = bench_nav / bench_nav.iloc[0]
        bench_map = dict(zip(bench["trade_date"], bench_nav))
        result["bench_nav"] = result["trade_date"].map(bench_map)
        # 超额收益
        bench_daily = dict(zip(bench["trade_date"], bench["pct_chg"] / 100.0))
        result["excess_return"] = result["daily_return"] - result["trade_date"].map(bench_daily)

    return result


def calc_portfolio_stats(nav_df):
    """
    计算组合绩效统计指标
    
    - 年化收益率 / 年化波动率
    - 夏普比率 (无风险 2%)
    - 最大回撤
    - 胜率 (正收益日占比)
    - 超额收益 / 信息比率
    """
    if nav_df.empty:
        return {}

    n = len(nav_df)
    if n < 2:
        return {"error": "数据不足"}

    total_ret = nav_df["nav"].iloc[-1] - 1
    years = n / 245  # 年化交易日数

    ann_ret = (1 + total_ret) ** (1 / years) - 1 if years > 0 else 0
    ann_vol = nav_df["daily_return"].std() * np.sqrt(245)
    sharpe = (ann_ret - 0.02) / ann_vol if ann_vol > 0 else 0

    # 最大回撤
    peak = nav_df["nav"].cummax()
    drawdown = (nav_df["nav"] - peak) / peak
    max_dd = drawdown.min()

    # 胜率
    win_rate = (nav_df["daily_return"] > 0).mean()

    stats = {
        "总收益率": f"{total_ret*100:.2f}%",
        "年化收益率": f"{ann_ret*100:.2f}%",
        "年化波动率": f"{ann_vol*100:.2f}%",
        "夏普比率": f"{sharpe:.2f}",
        "最大回撤": f"{max_dd*100:.2f}%",
        "胜率(日)": f"{win_rate*100:.1f}%",
        "交易日数": n,
        "年化(年)": f"{years:.1f}",
    }

    # 超额统计
    if "bench_nav" in nav_df.columns and "excess_return" in nav_df.columns:
        excess_total = nav_df["bench_nav"].iloc[-1]
        bench_ann = (excess_total) ** (1 / years) - 1 if years > 0 else 0
        tracking_error = nav_df["excess_return"].std() * np.sqrt(245)
        ir = (ann_ret - bench_ann) / tracking_error if tracking_error > 0 else 0
        stats.update({
            "基准总收益": f"{(excess_total-1)*100:.2f}%",
            "超额收益": f"{(total_ret - (excess_total-1))*100:.2f}%",
            "信息比率": f"{ir:.2f}",
        })

    return stats


# ── Brinson 归因分析 ────────────────────────────────

def brinson_attribution(pid, start_date=None, end_date=None):
    """
    Brinson 绩效归因: 行业配置效应 × 个股选择效应
    
    将组合收益分解为:
    - 行业配置收益 (sector allocation)
    - 个股选择收益 (stock selection)
    - 交互效应 (interaction)
    """
    info, holdings = get_portfolio(pid)
    if holdings is None or holdings.empty:
        return pd.DataFrame()

    from engine.query import sql as qsql

    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")

    codes = holdings["ts_code"].tolist()
    placeholders = ", ".join(["%s"] * len(codes))

    # 获取期初期末收盘价 + 行业
    first_last = qsql(
        None,
        f"SELECT d.ts_code, s.industry, "
        f"MIN(d.trade_date) FILTER (WHERE d.trade_date >= %s) as first_date, "
        f"MAX(d.trade_date) FILTER (WHERE d.trade_date <= %s) as last_date "
        f"FROM daily d JOIN stock_basic s ON d.ts_code=s.ts_code "
        f"WHERE d.ts_code IN ({placeholders}) "
        f"GROUP BY d.ts_code, s.industry",
        params=[start_date, end_date] + codes,
    )

    prices = qsql(
        None,
        f"SELECT ts_code, trade_date, close FROM daily "
        f"WHERE ts_code IN ({placeholders}) "
        f"AND trade_date IN (%s, %s)",
        params=codes + [start_date.replace("-",""), end_date.replace("-","")],
    )

    if prices.empty:
        return pd.DataFrame()

    # 行业基准收益（全市场该行业所有股票等权平均）
    stocks = qsql(None, "SELECT ts_code, industry FROM stock_basic")

    ind_codes = stocks.groupby("industry")["ts_code"].apply(list).to_dict()
    ind_returns = {}
    for ind, ind_stocks in ind_codes.items():
        sub = qsql(
            None,
            f"SELECT ts_code, trade_date, close FROM daily "
            f"WHERE ts_code = ANY(%s) AND trade_date IN (%s, %s)",
            params=[ind_stocks, start_date.replace("-",""), end_date.replace("-","")],
        )
        if not sub.empty and len(sub) >= 2:
            first_p = sub[sub["trade_date"] == sub["trade_date"].min()].set_index("ts_code")["close"]
            last_p = sub[sub["trade_date"] == sub["trade_date"].max()].set_index("ts_code")["close"]
            rets = (last_p / first_p - 1).mean()
            ind_returns[ind] = rets

    # 组合持仓收益率
    first_p = prices[prices["trade_date"] == prices["trade_date"].min()].set_index("ts_code")["close"]
    last_p = prices[prices["trade_date"] == prices["trade_date"].max()].set_index("ts_code")["close"]
    stock_rets = (last_p / first_p - 1)

    result_rows = []
    for _, row in holdings.iterrows():
        code = row["ts_code"]
        ind = row.get("industry", "")
        w = row["weight_pct"] / 100.0
        stock_ret = stock_rets.get(code, 0)
        bench_ind_ret = ind_returns.get(ind, 0)
        # 行业配置效应 = (组合权重 - 基准行业权重) × 行业基准收益
        # （简化：基准行业权重 = 全市场该行业占比）
        allocation = bench_ind_ret  # 粗略计算，精确需全行业权重
        selection = stock_ret - bench_ind_ret

        result_rows.append({
            "ts_code": code,
            "industry": ind,
            "权重%": round(w * 100, 1),
            "个股收益%": round(stock_ret * 100, 2),
            "行业基准%": round(bench_ind_ret * 100, 2) if pd.notna(bench_ind_ret) else "—",
            "选股效应%": round(selection * 100, 2),
        })

    return pd.DataFrame(result_rows).sort_values("权重%", ascending=False)