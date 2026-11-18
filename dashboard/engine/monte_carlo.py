"""
蒙特卡洛模拟引擎 — 对标 Bloomberg PORT / Wind 情景分析

功能:
  - 个股路径模拟 (GBM: Geometric Brownian Motion)
  - 组合蒙特卡洛 (N 条路径 → 风险分布)
  - 风险指标: VaR/CVaR/回撤概率/破产概率
"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from scipy.stats import norm

# ════════════════════════════════════════════════════════════════
# 个股路径模拟
# ════════════════════════════════════════════════════════════════

def simulate_gbm_paths(returns, n_sim=10000, horizon_days=252, seed=42):
    """
    几何布朗运动蒙特卡洛模拟

    Args:
        returns: 历史收益率 Series
        n_sim: 模拟路径数 (默认 10000)
        horizon_days: 预测天数 (默认 252 = 1年)
        seed: 随机种子

    返回:
        paths: ndarray [n_sim, horizon_days+1] (起始值=1)
        stats: dict {final_mean, final_median, final_std, var_95, var_99, cvar_95}
    """
    np.random.seed(seed)
    if returns.empty or len(returns) < 20:
        return None, {"error": "历史数据不足 (需≥20个交易日)"}

    mu = returns.mean()
    sigma = returns.std()

    if sigma == 0:
        return None, {"error": "波动率为零，无法模拟"}

    # GBM: dS/S = mu*dt + sigma*dW
    dt = 1.0 / 252  # 日频
    paths = np.zeros((n_sim, horizon_days + 1))
    paths[:, 0] = 1.0  # 起始净值归一化

    for t in range(1, horizon_days + 1):
        z = np.random.standard_normal(n_sim)
        paths[:, t] = paths[:, t-1] * np.exp(
            (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z
        )

    final = paths[:, -1]

    # 风险指标
    var_95 = np.percentile(final - 1, 5) * 100  # 95% VaR (%)
    var_99 = np.percentile(final - 1, 1) * 100  # 99% VaR (%)
    # CVaR (Expected Shortfall)
    tail = final[final <= np.percentile(final, 5)]
    cvar_95 = (tail.mean() - 1) * 100 if len(tail) > 0 else var_95

    # 亏损概率
    loss_prob = (final < 1).mean() * 100

    stats = {
        "final_mean": round(float(final.mean()), 4),
        "final_median": round(float(np.median(final)), 4),
        "final_std": round(float(final.std()), 4),
        "var_95_pct": round(float(var_95), 2),
        "var_99_pct": round(float(var_99), 2),
        "cvar_95_pct": round(float(cvar_95), 2),
        "loss_prob_pct": round(float(loss_prob), 1),
        "annual_return_pct": round(float(((final.mean())**(252/horizon_days) - 1)*100), 2),
        "annual_vol_pct": round(float(sigma * np.sqrt(252) * 100), 2),
        "sharpe_forward": round(float((mu * 252) / (sigma * np.sqrt(252))), 3) if sigma > 0 else 0,
    }

    return paths, stats


def simulate_gbm_with_dividend(returns, div_yield=0.02, n_sim=10000, horizon=252):
    """含股息再投资的 GBM 模拟（同上但 mu = mu_hist + div_yield）"""
    mu = returns.mean() + div_yield / 252
    sigma = returns.std()
    np.random.seed(42)
    dt = 1.0 / 252
    paths = np.zeros((n_sim, horizon + 1))
    paths[:, 0] = 1.0
    for t in range(1, horizon + 1):
        z = np.random.standard_normal(n_sim)
        paths[:, t] = paths[:, t-1] * np.exp(
            (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z
        )
    final = paths[:, -1]
    var_95 = np.percentile(final - 1, 5) * 100
    return paths, {
        "final_mean": round(final.mean(), 4),
        "var_95_pct": round(var_95, 2),
        "annual_return_pct": round(((final.mean())**(252/horizon) - 1)*100, 2),
    }

# ════════════════════════════════════════════════════════════════
# 组合蒙特卡洛
# ════════════════════════════════════════════════════════════════

def portfolio_monte_carlo(holdings_returns: dict, weights: list,
                          n_sim=10000, horizon_days=252, seed=42):
    """
    多资产组合蒙特卡洛

    Args:
        holdings_returns: {ts_code: pd.Series(returns)}
        weights: list[float] (需总和=1)
        n_sim: 模拟路径数
        horizon_days: 天数

    返回:
        paths: ndarray [n_sim, horizon_days+1]
        stats: dict
        contribution: dict {code: {weight, mean_return, vol_contrib}}
    """
    np.random.seed(seed)
    codes = list(holdings_returns.keys())
    n = len(codes)

    if abs(sum(weights) - 1.0) > 0.01:
        weights = np.array(weights) / sum(weights)

    # 对齐日期
    common_dates = None
    for code, rets in holdings_returns.items():
        if common_dates is None:
            common_dates = set(rets.index)
        else:
            common_dates = common_dates.intersection(rets.index)

    if not common_dates or len(common_dates) < 20:
        return None, {"error": "共同交易日不足"}, {}

    common_dates = sorted(common_dates)

    # 构建收益矩阵
    ret_matrix = np.column_stack([
        holdings_returns[code].loc[common_dates].values for code in codes
    ])

    mu_vec = ret_matrix.mean(axis=0)
    cov_mat = np.cov(ret_matrix, rowvar=False)

    # 组合参数
    port_mu = np.dot(weights, mu_vec)
    port_sigma = np.sqrt(np.dot(weights, np.dot(cov_mat, weights)))

    if port_sigma == 0:
        return None, {"error": "组合波动率为零"}, {}

    dt = 1.0 / 252
    paths = np.zeros((n_sim, horizon_days + 1))
    paths[:, 0] = 1.0

    for t in range(1, horizon_days + 1):
        z = np.random.multivariate_normal(np.zeros(n), cov_mat, size=n_sim)
        port_returns = np.dot(z, weights)
        paths[:, t] = paths[:, t-1] * np.exp(
            (port_mu - 0.5 * port_sigma**2) * dt + port_sigma * np.sqrt(dt) *
            (port_returns / port_sigma)  # 修正: 确保正确的相关性结构
        )

    final = paths[:, -1]
    var_95 = np.percentile(final - 1, 5) * 100
    var_99 = np.percentile(final - 1, 1) * 100
    tail = final[final <= np.percentile(final, 5)]
    cvar_95 = (tail.mean() - 1) * 100 if len(tail) > 0 else var_95

    # 最大回撤 (沿每条路径)
    max_dds = []
    for p in paths:
        cummax = np.maximum.accumulate(p)
        dd = (p - cummax) / cummax
        max_dds.append(dd.min())
    avg_max_dd = np.mean(max_dds) * 100
    p5_max_dd = np.percentile(max_dds, 5) * 100

    # 风险贡献分解
    risk_contrib = {}
    for i, code in enumerate(codes):
        marginal = np.dot(cov_mat[i], weights) / port_sigma
        contrib = weights[i] * marginal / port_sigma * 100
        risk_contrib[code] = {
            "weight": round(weights[i], 4),
            "mean_return": round(mu_vec[i] * 100, 3),
            "vol": round(np.sqrt(cov_mat[i, i]) * 100, 3),
            "risk_contrib_pct": round(contrib, 2),
        }

    stats = {
        "port_mean_return_ann": round(port_mu * 252 * 100, 2),
        "port_vol_ann": round(port_sigma * np.sqrt(252) * 100, 2),
        "sharpe_forward": round(port_mu / port_sigma * np.sqrt(252), 3) if port_sigma > 0 else 0,
        "var_95_pct": round(var_95, 2),
        "var_99_pct": round(var_99, 2),
        "cvar_95_pct": round(cvar_95, 2),
        "loss_prob_pct": round((final < 1).mean() * 100, 1),
        "avg_max_dd_pct": round(avg_max_dd, 2),
        "p5_max_dd_pct": round(p5_max_dd, 2),
        "final_median": round(np.median(final), 4),
        "n_sim": n_sim,
        "horizon_days": horizon_days,
    }

    return paths, stats, risk_contrib


# ════════════════════════════════════════════════════════════════
# 分布分位数
# ════════════════════════════════════════════════════════════════

def distribution_summary(paths, percentiles=[1, 5, 10, 25, 50, 75, 90, 95, 99]):
    """模拟路径终值分布摘要"""
    if paths is None:
        return {}
    final = paths[:, -1]
    result = {}
    for p in percentiles:
        val = np.percentile(final, p)
        result[f"p{p}"] = round(float(val), 4)
    result["mean"] = round(float(final.mean()), 4)
    result["std"] = round(float(final.std()), 4)
    return result