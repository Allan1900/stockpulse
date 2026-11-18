"""
风险分析引擎 — 对标 Bloomberg PORT / Wind 风险管理模块

核心指标:
  - VaR (历史法/参数法) + CVaR
  - 最大回撤 + 回撤持续时间
  - Beta (vs 沪深300) + Alpha
  - Sharpe / Sortino / Calmar / Information 比率
  - 胜率 / 盈亏比 / 期望值
"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from engine.query import sql as _sql


def get_benchmark_returns(start_date, end_date, bench_code="000300.SH"):
    """获取基准指数(默认沪深300)日收益率序列"""
    df = _sql(None, """
        SELECT trade_date, pct_chg
        FROM index_daily
        WHERE ts_code = %s
          AND trade_date >= %s AND trade_date <= %s
        ORDER BY trade_date
    """, params=[bench_code, start_date, end_date])
    if df.empty:
        # 降级: 用上证指数
        df = _sql(None, """
            SELECT trade_date, pct_chg
            FROM index_daily
            WHERE ts_code = '000001.SH'
              AND trade_date >= %s AND trade_date <= %s
            ORDER BY trade_date
        """, params=[start_date, end_date])
    df["return"] = df["pct_chg"] / 100.0
    return df[["trade_date", "return"]].copy()


def get_stock_returns(ts_code, start_date, end_date):
    """获取个股日收益率序列"""
    df = _sql(None, """
        SELECT trade_date, pct_chg
        FROM daily
        WHERE ts_code = %s
          AND trade_date >= %s AND trade_date <= %s
        ORDER BY trade_date
    """, params=[ts_code, start_date, end_date])
    if df.empty:
        return pd.DataFrame()
    df["return"] = df["pct_chg"] / 100.0
    return df[["trade_date", "return"]].copy()


def compute_var(returns, alpha=0.05):
    """
    Value at Risk — 历史模拟法
    returns: 收益率 Series
    alpha: 置信水平 (默认 95%, alpha=0.05)
    返回: {historical_var, parametric_var}
    """
    if returns.empty or len(returns) < 20:
        return {"historical_var": None, "parametric_var": None}
    
    # 历史模拟法
    hist_var = np.percentile(returns, alpha * 100)
    
    # 参数法 (正态分布)
    mu = returns.mean()
    sigma = returns.std()
    from scipy.stats import norm
    parametric_var = mu + sigma * norm.ppf(alpha)
    
    return {
        "historical_var_95": round(float(hist_var) * 100, 2),
        "parametric_var_95": round(float(parametric_var) * 100, 2),
    }


def compute_cvar(returns, alpha=0.05):
    """
    CVaR / Expected Shortfall — 超过 VaR 的尾部风险
    """
    if returns.empty or len(returns) < 20:
        return None
    
    var = np.percentile(returns, alpha * 100)
    tail = returns[returns <= var]
    cvar = tail.mean() if not tail.empty else var
    return round(float(cvar) * 100, 2)


def compute_max_drawdown(returns):
    """
    最大回撤 + 回撤持续时间
    返回: {max_drawdown_pct, max_drawdown_duration_days, drawdown_series}
    """
    if returns.empty or len(returns) < 5:
        return {"max_drawdown_pct": None, "max_drawdown_duration_days": None}
    
    cum = (1 + returns).cumprod()
    rolling_max = cum.cummax()
    drawdown = (cum - rolling_max) / rolling_max
    
    max_dd = drawdown.min()
    
    # 计算最长回撤持续时间
    is_dd = drawdown < 0
    dd_streaks = []
    current_streak = 0
    for flag in is_dd:
        if flag:
            current_streak += 1
        else:
            if current_streak > 0:
                dd_streaks.append(current_streak)
            current_streak = 0
    if current_streak > 0:
        dd_streaks.append(current_streak)
    
    max_duration = max(dd_streaks) if dd_streaks else 0
    
    return {
        "max_drawdown_pct": round(float(max_dd) * 100, 2),
        "max_drawdown_duration_days": max_duration,
    }


def compute_beta_alpha(stock_returns, bench_returns):
    """
    Beta (市场风险暴露) + Alpha (超额收益)
    使用线性回归: stock_return = alpha + beta * bench_return + epsilon
    """
    merged = pd.merge(
        stock_returns, bench_returns,
        on="trade_date", suffixes=("_stock", "_bench")
    )
    if len(merged) < 20:
        return {"beta": None, "alpha": None}
    
    x = merged["return_bench"].values
    y = merged["return_stock"].values
    
    if x.std() == 0:
        return {"beta": None, "alpha": None}
    
    # OLS: beta = cov(x,y) / var(x)
    beta = np.cov(x, y)[0, 1] / np.var(x)
    
    # Annualized alpha
    rf_daily = 0.02 / 252  # 假设无风险利率 2%
    alpha = (y.mean() - rf_daily) - beta * (x.mean() - rf_daily)
    alpha_annual = alpha * 252
    
    return {
        "beta": round(float(beta), 4),
        "alpha_annual": round(float(alpha_annual) * 100, 2),  # %
    }


def compute_sharpe_ratio(returns, rf_annual=0.02):
    """
    Sharpe Ratio — 年化夏普比率
    """
    if returns.empty or len(returns) < 20 or returns.std() == 0:
        return None
    
    rf_daily = rf_annual / 252
    excess = returns - rf_daily
    sharpe = np.sqrt(252) * excess.mean() / returns.std()
    return round(float(sharpe), 4)


def compute_sortino_ratio(returns, rf_annual=0.02):
    """
    Sortino Ratio — 只考虑下行波动
    """
    if returns.empty or len(returns) < 20:
        return None
    
    rf_daily = rf_annual / 252
    excess = returns.mean() - rf_daily
    
    downside = returns[returns < 0]
    if len(downside) == 0 or downside.std() == 0:
        return None
    
    downside_std = downside.std()
    sortino = np.sqrt(252) * excess / downside_std
    return round(float(sortino), 4)


def compute_calmar_ratio(returns):
    """
    Calmar Ratio — 年化收益 / 最大回撤
    """
    if returns.empty or len(returns) < 20:
        return None
    
    dd_info = compute_max_drawdown(returns)
    max_dd = dd_info["max_drawdown_pct"]
    if max_dd is None or max_dd == 0:
        return None
    
    total_return = (1 + returns).prod()
    years = len(returns) / 252
    ann_return = total_return ** (1 / years) - 1 if years > 0 else 0
    
    calmar = (ann_return * 100) / abs(max_dd)
    return round(float(calmar), 4)


def compute_win_rate(returns):
    """胜率 — 正收益天数占比"""
    if returns.empty:
        return None
    wins = (returns > 0).sum()
    total = len(returns)
    return round(wins / total * 100, 2)


def compute_profit_factor(returns):
    """盈亏比 — 总盈利 / 总亏损"""
    if returns.empty:
        return None
    total_gain = returns[returns > 0].sum()
    total_loss = abs(returns[returns < 0].sum())
    if total_loss == 0:
        return None
    return round(float(total_gain / total_loss), 4)


def compute_tracking_error(stock_returns, bench_returns):
    """跟踪误差 — 主动风险"""
    merged = pd.merge(
        stock_returns, bench_returns,
        on="trade_date", suffixes=("_stock", "_bench")
    )
    if len(merged) < 20:
        return None
    
    diff = merged["return_stock"] - merged["return_bench"]
    te = diff.std() * np.sqrt(252) * 100  # 年化 %
    return round(float(te), 2)


def compute_information_ratio(stock_returns, bench_returns):
    """信息比率 — 主动收益 / 跟踪误差"""
    merged = pd.merge(
        stock_returns, bench_returns,
        on="trade_date", suffixes=("_stock", "_bench")
    )
    if len(merged) < 20:
        return None
    
    diff = merged["return_stock"] - merged["return_bench"]
    active_return = diff.mean() * 252
    te = diff.std() * np.sqrt(252)
    if te == 0:
        return None
    ir = active_return / te
    return round(float(ir), 4)


def full_risk_report(ts_code, start_date, end_date, bench_code="000300.SH"):
    """
    完整风险分析报告 — 一键生成个股/组合全部风险指标
    
    返回 dict 包含全部指标 + 说明
    """
    stock_rets = get_stock_returns(ts_code, start_date, end_date)
    bench_rets = get_benchmark_returns(start_date, end_date, bench_code)
    
    if stock_rets.empty:
        return {"error": f"无数据: {ts_code} 在 {start_date}~{end_date}"}
    
    result = {}
    
    # 基础统计
    result["观测天数"] = len(stock_rets)
    result["年化收益率"] = round(float(
        ((1 + stock_rets["return"]).prod() ** (252 / len(stock_rets)) - 1) * 100
    ), 2) if len(stock_rets) > 0 else None
    result["年化波动率"] = round(float(
        stock_rets["return"].std() * np.sqrt(252) * 100
    ), 2)
    
    # VaR
    var_info = compute_var(stock_rets["return"])
    result.update(var_info)
    
    # CVaR
    result["CVaR_95"] = compute_cvar(stock_rets["return"])
    
    # 最大回撤
    dd_info = compute_max_drawdown(stock_rets["return"])
    result.update(dd_info)
    
    # Beta & Alpha
    ba = compute_beta_alpha(stock_rets["return"], bench_rets["return"])
    result.update(ba)
    
    # 风险调整收益
    result["Sharpe"] = compute_sharpe_ratio(stock_rets["return"])
    result["Sortino"] = compute_sortino_ratio(stock_rets["return"])
    result["Calmar"] = compute_calmar_ratio(stock_rets["return"])
    
    # 交易统计
    result["胜率(%)"] = compute_win_rate(stock_rets["return"])
    result["盈亏比"] = compute_profit_factor(stock_rets["return"])
    
    # 相对基准
    result["跟踪误差(%)"] = compute_tracking_error(
        stock_rets["return"], bench_rets["return"]
    )
    result["信息比率"] = compute_information_ratio(
        stock_rets["return"], bench_rets["return"]
    )
    
    return result


def portfolio_risk_report(holdings, start_date, end_date, bench_code="000300.SH"):
    """
    组合风险分析 — 多只股票加权组合风险
    
    holdings: [{ts_code, weight}, ...] 权重之和应为1
    """
    bench_rets = get_benchmark_returns(start_date, end_date, bench_code)
    
    # 获取所有个股收益并拼接
    portfolio_rets = None
    individual = {}
    
    for h in holdings:
        code = h["ts_code"]
        weight = h.get("weight", 1.0 / len(holdings))
        
        rets = get_stock_returns(code, start_date, end_date)
        if rets.empty:
            continue
        
        rets = rets.rename(columns={"return": f"ret_{code}"})
        individual[code] = {"weight": weight, "returns": rets}
    
    if not individual:
        return {"error": "无有效持仓数据"}
    
    # 合并所有收益数据
    merged = None
    for code, data in individual.items():
        if merged is None:
            merged = data["returns"].copy()
            merged = merged.rename(columns={f"ret_{code}": "return"})
            merged["return"] *= data["weight"]
        else:
            r = data["returns"].rename(columns={f"ret_{code}": "return"})
            merged = pd.merge(merged, r, on="trade_date", how="outer")
            merged["return"] += r["return"] * data["weight"]
    
    if merged is None or merged.empty:
        return {"error": "组合收益计算失败"}
    
    merged = merged.sort_values("trade_date").ffill().bfill()
    
    # 用个股风险报告函数
    result = {
        "观测天数": len(merged),
        "持仓数": len(holdings),
    }
    
    result["年化收益率"] = round(float(
        ((1 + merged["return"]).prod() ** (252 / len(merged)) - 1) * 100
    ), 2) if len(merged) > 0 else None
    result["年化波动率"] = round(float(
        merged["return"].std() * np.sqrt(252) * 100
    ), 2)
    
    var_info = compute_var(merged["return"])
    result.update(var_info)
    result["CVaR_95"] = compute_cvar(merged["return"])
    
    dd_info = compute_max_drawdown(merged["return"])
    result.update(dd_info)
    
    ba = compute_beta_alpha(merged["return"], bench_rets["return"])
    result.update(ba)
    
    result["Sharpe"] = compute_sharpe_ratio(merged["return"])
    result["Sortino"] = compute_sortino_ratio(merged["return"])
    result["Calmar"] = compute_calmar_ratio(merged["return"])
    result["胜率(%)"] = compute_win_rate(merged["return"])
    result["盈亏比"] = compute_profit_factor(merged["return"])
    
    return result


def stress_test_scenarios(ts_code, start_date, end_date):
    """
    压力测试 — 3 种情景模拟:
    - 市场大跌 (-5%) 情景
    - 高波动 (+50% vol) 情景
    - 流动性冲击 (-2% 连续5日) 情景
    """
    stock_rets = get_stock_returns(ts_code, start_date, end_date)
    if stock_rets.empty:
        return {"error": f"无数据: {ts_code}"}
    
    rets = stock_rets["return"].values
    mu = rets.mean()
    sigma = rets.std()
    
    scenarios = {}
    
    # 情景1: 市场大跌 -5% 单日
    scenarios["market_crash"] = {
        "scenario": "市场大跌 (-5% 单日冲击)",
        "impact_pct": round(float(mu - 0.05) * 100, 2),
        "var_impact": "≈日跌幅5%",
    }
    
    # 情景2: 波动率翻倍
    vol_double = sigma * 2
    scenarios["vol_shock"] = {
        "scenario": "波动率翻倍 (+100% vol)",
        "impact_pct": round(float((mu - vol_double * 2)) * 100, 2),
        "var_impact": f"≈日VaR(95%)升至 {round(float(vol_double * 1.645) * 100, 2)}%",
    }
    
    # 情景3: 连续5日下跌2%
    cum_loss = (1 - 0.02) ** 5 - 1
    scenarios["liquidity_shock"] = {
        "scenario": "流动性冲击 (连跌5日 -2%/日)",
        "impact_pct": round(float(cum_loss * 100), 2),
        "var_impact": "≈累计回撤 -9.6%",
    }
    
    return scenarios
# ════════════════════════════════════════════════════════════════
# 风险分解 — Barra 风格因子归因
# ════════════════════════════════════════════════════════════════

def factor_risk_decomposition(ts_code, start_date, end_date):
    """因子风险分解: 市场因子 + 行业因子 → 风险占比"""
    from engine.query import sql as _sql
    stock = get_stock_returns(ts_code, start_date, end_date)
    if stock.empty: return {"error": f"无数据: {ts_code}"}
    market = get_benchmark_returns(start_date, end_date)
    ind_info = _sql(None, "SELECT industry FROM stock_basic WHERE ts_code=%s", [ts_code])
    industry_name = ind_info.iloc[0]["industry"] if not ind_info.empty else None

    industry_returns = None
    if industry_name:
        ind_ret = _sql(None, """WITH ind_stocks AS (SELECT ts_code FROM stock_basic WHERE industry=%s)
            SELECT d.trade_date, AVG(d.pct_chg)/100 AS ind_return FROM daily d
            JOIN ind_stocks s ON d.ts_code = s.ts_code
            WHERE d.trade_date>=%s AND d.trade_date<=%s
            GROUP BY d.trade_date ORDER BY d.trade_date""",
            params=[industry_name, start_date, end_date])
        if not ind_ret.empty:
            industry_returns = ind_ret
            industry_returns.columns = ["trade_date", "return"]

    merged = stock.merge(market, on="trade_date", suffixes=("_stock", "_mkt"))
    if industry_returns is not None:
        merged = merged.merge(industry_returns, on="trade_date", how="left")
        merged["return"] = merged["return"].fillna(merged["return_mkt"])

    if len(merged) < 20: return {"error": "数据不足"}

    y = merged["return_stock"].values
    x_mkt = merged["return_mkt"].values
    beta_mkt = np.cov(x_mkt, y)[0,1]/np.var(x_mkt) if np.var(x_mkt)>0 else 0
    total_var = np.var(y)

    if industry_returns is not None:
        x_ind = merged["return"].fillna(0).values
        X = np.column_stack([np.ones(len(x_mkt)), x_mkt, x_ind])
        try:
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            predicted = X @ beta
            explained = np.var(predicted)
            mkt_contrib = beta[1]**2 * np.var(x_mkt) / total_var * 100
            ind_contrib = beta[2]**2 * np.var(x_ind) / total_var * 100
            market_risk_pct = round(mkt_contrib, 1)
            ind_risk_pct = round(ind_contrib, 1)
            r_sq = round(explained/total_var*100, 1)
        except:
            market_risk_pct = round(beta_mkt**2*np.var(x_mkt)/total_var*100,1) if total_var>0 else 0
            ind_risk_pct = 0
            r_sq = 0
    else:
        market_risk_pct = round(beta_mkt**2*np.var(x_mkt)/total_var*100,1) if total_var>0 else 0
        ind_risk_pct = 0
        r_sq = market_risk_pct

    idio_pct = round(max(0, 100-market_risk_pct-ind_risk_pct), 1)
    return {"market_risk_pct": market_risk_pct, "industry_risk_pct": ind_risk_pct,
        "idiosyncratic_pct": idio_pct, "total_risk_ann": round(stock["return"].std()*np.sqrt(252)*100,2),
        "beta": round(beta_mkt,4), "r_squared": r_sq}

# ════════════════════════════════════════════════════════════════
# 极值理论 (EVT) — 尾部风险
# ════════════════════════════════════════════════════════════════

def tail_risk_analysis(returns, threshold_pct=5):
    """极值理论尾部风险: VaR/CVaR/尾部指数/聚集效应"""
    if returns.empty or len(returns) < 50:
        return {"error": "历史数据不足(需≥50交易日)"}
    threshold = np.percentile(returns, threshold_pct)
    tail = returns[returns <= threshold]
    if tail.empty:
        return {"error": "尾部数据为空"}
    sorted_abs = np.sort(np.abs(returns[returns<0].values))
    k = max(5, int(len(sorted_abs)*0.1))
    hill = np.mean(np.log(sorted_abs[-k:]/sorted_abs[-k-1])) if k < len(sorted_abs) else 0

    is_tail = returns <= threshold
    clusters = []; cur = 0
    for flag in is_tail:
        cur = cur+1 if flag else 0
        if not flag and cur > 0: clusters.append(cur); cur=0
    if cur > 0: clusters.append(cur)

    return {"tail_loss_avg_pct": round(tail.mean()*100,2),
        "tail_var_95_pct": round(float(np.percentile(returns,5))*100,2),
        "tail_var_99_pct": round(float(np.percentile(returns,1))*100,2),
        "tail_skewness": round(float(tail.skew()),4),
        "hill_estimator": round(float(hill),4),
        "max_single_loss_pct": round(float(returns.min())*100,2),
        "avg_cluster_days": round(float(np.mean(clusters) if clusters else 0),1),
        "tail_obs_count": len(tail)}

# ════════════════════════════════════════════════════════════════
# 压力测试升级 — 多情景模拟
# ════════════════════════════════════════════════════════════════

def scenario_stress_test(ts_code, start_date, end_date):
    """增强压力测试: 4种情景 vs 原3种"""
    stock_rets = get_stock_returns(ts_code, start_date, end_date)
    if stock_rets.empty:
        return {"error": f"无数据: {ts_code}"}
    rets = stock_rets["return"].values
    mu = rets.mean(); sigma = rets.std()
    if sigma == 0: return {"error": "波动率为零"}
    from engine.query import sql_one
    # 获取行业信息
    ind_info = sql_one(None, "SELECT industry, name FROM stock_basic WHERE ts_code=%s", [ts_code])
    industry = ind_info["industry"] if ind_info else "未知"
    stock_name = ind_info["name"] if ind_info else ts_code

    # 获取当前PE
    pe_info = sql_one(None, "SELECT pe_ttm FROM daily_basic WHERE ts_code=%s ORDER BY trade_date DESC LIMIT 1", [ts_code])
    current_pe = pe_info["pe_ttm"] if pe_info else None

    scenarios = {}

    # S1: 市场崩盘 (-10% 单日, 2008/2020 式)
    impact_s1 = beta_from_returns(rets, mu, sigma) * (-0.10)
    scenarios["market_crash"] = {
        "name": "市场崩盘 (−10% 单日冲击)",
        "trigger": "类似 2008 全球金融危机或 2020 新冠熔断",
        "impact_pct": round(float(impact_s1) * 100, 2),
        "bearing": "max",
    }

    # S2: 行业利空 (−8% 行业冲击)
    scenarios["sector_shock"] = {
        "name": f"行业利空 ({industry} −8% 冲击)",
        "trigger": "行业政策突变 / 技术路线颠覆 / 出口管制升级",
        "impact_pct": round(float(mu - 0.08) * 100, 2),
        "bearing": "high",
    }

    # S3: 通胀/加息冲击
    scenarios["rate_hike"] = {
        "name": "加息冲击 (利率 +200bp, 估值压缩)",
        "trigger": "美联储/央行意外加息，高估值股票承压",
        "impact_pct": round(float(mu - 0.06) * 100, 2) if current_pe and current_pe > 30 else round(float(mu - 0.03) * 100, 2),
        "bearing": "medium",
    }

    # S4: 流动性危机 (连续 10 日阴跌)
    cum_liq = (1 - 0.015) ** 10 - 1
    scenarios["liquidity_crisis"] = {
        "name": "流动性危机 (连跌10日 −1.5%/日)",
        "trigger": "量化基金去杠杆 / 赎回潮 / 流动性枯竭",
        "impact_pct": round(float(cum_liq * 100), 2),
        "bearing": "high",
    }

    return {"stock_name": stock_name, "industry": industry, "current_pe": current_pe, "scenarios": scenarios}

def beta_from_returns(rets, mu, sigma):
    """估算 Beta (无基准时用简化方法)"""
    return 1.0  # 默认 Beta=1, 个股 risk_analysis 已有精确计算
