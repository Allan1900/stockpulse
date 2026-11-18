"""
回测引擎升级 — 并行回测 + 参数扫描 + 绩效报告

升级内容:
  - 并行回测: 多股票同时运行
  - 参数扫描: Grid Search 优化策略参数
  - 绩效报告: 整合风险分析模块的完整指标
  - 多策略对比: 同时对比多个策略表现
"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from engine.query import query as _q

# ── 回测策略函数库 ──────────────────────────────────
def strategy_ma_cross(df, fast=5, slow=20):
    """MA 金叉/死叉策略"""
    df = df.copy()
    ma_fast = df["close"].rolling(fast).mean()
    ma_slow = df["close"].rolling(slow).mean()
    df["signal"] = 0
    prev_diff = (ma_fast.shift(1) - ma_slow.shift(1))
    curr_diff = (ma_fast - ma_slow)
    df.loc[(prev_diff <= 0) & (curr_diff > 0), "signal"] = 1   # 金叉→买入
    df.loc[(prev_diff >= 0) & (curr_diff < 0), "signal"] = -1  # 死叉→卖出
    return df


def strategy_macd_cross(df, fast=12, slow=26, signal_p=9):
    """MACD 金叉/死叉策略"""
    df = df.copy()
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal_p, adjust=False).mean()
    df["signal"] = 0
    df.loc[(dif.shift(1) <= dea.shift(1)) & (dif > dea), "signal"] = 1
    df.loc[(dif.shift(1) >= dea.shift(1)) & (dif < dea), "signal"] = -1
    return df


def strategy_rsi_reversal(df, period=14, overbought=70, oversold=30):
    """RSI 超买超卖反转策略"""
    df = df.copy()
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    df["signal"] = 0
    df.loc[rsi.shift(1) >= oversold, "signal"] = 1   # 脱离超卖→买入
    df.loc[rsi.shift(1) <= overbought, "signal"] = -1  # 进入超买→卖出
    # 修正: 只有从超卖区出来才买入
    df.loc[~((rsi.shift(1) < oversold) & (rsi >= oversold)), "signal"] = 0
    df.loc[~((rsi.shift(1) > overbought) & (rsi <= overbought)), "signal"] = 0
    # 简化版: RSI < oversold 买入, RSI > overbought 卖出
    df.loc[rsi < oversold, "signal"] = 1
    df.loc[rsi > overbought, "signal"] = -1
    return df


def strategy_boll_breakout(df, period=20, std_mul=2.0):
    """布林带突破策略"""
    df = df.copy()
    middle = df["close"].rolling(period).mean()
    std = df["close"].rolling(period).std()
    upper = middle + std_mul * std
    lower = middle - std_mul * std
    df["signal"] = 0
    df.loc[df["close"] < lower, "signal"] = 1    # 跌破下轨→买入
    df.loc[df["close"] > upper, "signal"] = -1   # 突破上轨→卖出
    return df


STRATEGIES = {
    "MA金叉死叉": {"func": strategy_ma_cross, "params": {"fast": (2, 30, 2), "slow": (10, 60, 5)}},
    "MACD金叉死叉": {"func": strategy_macd_cross, "params": {"fast": (8, 20, 2), "slow": (20, 40, 4), "signal_p": (5, 15, 2)}},
    "RSI超买超卖": {"func": strategy_rsi_reversal, "params": {"period": (6, 24, 3), "overbought": (65, 85, 5), "oversold": (15, 35, 5)}},
    "布林带突破": {"func": strategy_boll_breakout, "params": {"period": (10, 40, 5), "std_mul": (1.5, 3.0, 0.5)}},
}


# ── 回测运行器 ──────────────────────────────────────
def run_single_backtest(df, commission_pct=0.03, slippage_pct=0.05):
    """
    对给定 DataFrame（已含 signal 列）运行回测
    
    返回: {"equity_curve": Series, "trades": list, "metrics": dict}
    """
    if df.empty or "signal" not in df.columns:
        return {"equity_curve": pd.Series([1.0]), "trades": [], "metrics": {}}

    df = df.sort_values("trade_date").reset_index(drop=True)
    trades = []
    position = 0
    entry_price = 0
    entry_date = None
    equity = [1.0]
    cost = (commission_pct + slippage_pct) / 100

    for i in range(1, len(df)):
        sig = df.iloc[i - 1]["signal"]

        if sig == 1 and position == 0:
            position = 1
            entry_price = df.iloc[i]["open"]
            entry_date = df.iloc[i]["trade_date"]
        elif sig == -1 and position == 1:
            position = 0
            exit_price = df.iloc[i]["open"]
            exit_date = df.iloc[i]["trade_date"]
            ret = (exit_price / entry_price - 1) - cost * 2
            trades.append({
                "买入日期": entry_date, "买入价": round(entry_price, 2),
                "卖出日期": exit_date, "卖出价": round(exit_price, 2),
                "收益率%": round(ret * 100, 2),
                "持有天数": (pd.to_datetime(exit_date) - pd.to_datetime(entry_date)).days,
            })

        if position == 1:
            daily_ret = df.iloc[i]["close"] / df.iloc[i - 1]["close"] - 1
        else:
            daily_ret = 0
        equity.append(equity[-1] * (1 + daily_ret))

    # 平仓
    if position == 1:
        exit_price = df.iloc[-1]["close"]
        ret = (exit_price / entry_price - 1) - cost * 2
        trades.append({
            "买入日期": entry_date, "买入价": round(entry_price, 2),
            "卖出日期": df.iloc[-1]["trade_date"], "卖出价": round(exit_price, 2),
            "收益率%": round(ret * 100, 2),
            "持有天数": (pd.to_datetime(df.iloc[-1]["trade_date"]) - pd.to_datetime(entry_date)).days,
        })

    equity_series = pd.Series(equity, name="策略净值")

    # ── 绩效指标 ──
    total_ret = equity_series.iloc[-1] - 1
    hold_ret = df["close"].iloc[-1] / df["close"].iloc[0] - 1
    n_days = len(df)
    ann_ret = (1 + total_ret) ** (252 / n_days) - 1 if n_days >= 20 else total_ret

    cummax = equity_series.cummax()
    drawdown = (equity_series - cummax) / cummax
    max_dd = drawdown.min()

    daily_rets = equity_series.pct_change().dropna()
    sharpe = np.sqrt(252) * daily_rets.mean() / daily_rets.std() if daily_rets.std() > 0 else 0

    # 下行波动 (Sortino)
    downside = daily_rets[daily_rets < 0]
    rf_daily = 0.02 / 252
    sortino = np.sqrt(252) * (daily_rets.mean() - rf_daily) / downside.std() if len(downside) > 0 and downside.std() > 0 else 0

    # 最大回撤持续天数
    is_dd = drawdown < 0
    dd_streaks = []
    cur = 0
    for flag in is_dd:
        cur = cur + 1 if flag else 0
        if flag == 0 and cur > 0:
            dd_streaks.append(cur)
            cur = 0
    if cur > 0:
        dd_streaks.append(cur)
    max_dd_days = max(dd_streaks) if dd_streaks else 0

    metrics = {
        "总收益率%": round(total_ret * 100, 2),
        "年化收益率%": round(ann_ret * 100, 2) if n_days >= 20 else round(total_ret * 100, 2),
        "最大回撤%": round(max_dd * 100, 2),
        "最长回撤期(天)": max_dd_days,
        "夏普比率": round(sharpe, 3),
        "索提诺比率": round(sortino, 3),
        "交易次数": len(trades),
        "胜率%": round(sum(1 for t in trades if t["收益率%"] > 0) / len(trades) * 100, 1) if trades else 0,
        "平均盈利%": round(np.mean([t["收益率%"] for t in trades if t["收益率%"] > 0]), 2) if any(t["收益率%"] > 0 for t in trades) else 0,
        "平均亏损%": round(np.mean([t["收益率%"] for t in trades if t["收益率%"] <= 0]), 2) if any(t["收益率%"] <= 0 for t in trades) else 0,
        "持有收益率%": round(hold_ret * 100, 2),
    }

    return {"equity_curve": equity_series, "trades": trades, "metrics": metrics}


def backtest_single(code, start, end, strategy_name, strategy_params, commission=0.03, slippage=0.05):
    """单股票单策略回测"""
    df = _q(stocks=code,
            fields="trade_date,open,high,low,close,vol,amount,pct_chg",
            start_date=start, end_date=end)
    if df.empty:
        return None
    df = df.sort_values("trade_date").reset_index(drop=True)
    strategy_func = STRATEGIES[strategy_name]["func"]
    df = strategy_func(df, **strategy_params)
    result = run_single_backtest(df, commission, slippage)
    result["df"] = df
    result["code"] = code
    return result


def parallel_backtest(codes, start, end, strategy_name, strategy_params,
                      commission=0.03, slippage=0.05, max_workers=4):
    """多股票并行回测"""
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                backtest_single, code, start, end,
                strategy_name, strategy_params, commission, slippage
            ): code for code in codes
        }
        for future in as_completed(futures):
            code = futures[future]
            try:
                result = future.result()
                if result:
                    results.append(result)
            except Exception as e:
                pass
    return results


def param_grid_search(code, start, end, strategy_name, param_ranges,
                      commission=0.03, slippage=0.05):
    """参数网格扫描 — 遍历参数组合找最优"""
    from itertools import product

    param_keys = list(param_ranges.keys())
    param_values = list(param_ranges.values())

    # 生成所有组合
    all_combs = list(product(*param_values))
    if len(all_combs) > 200:
        # 限制扫描上限
        step = max(1, len(all_combs) // 200)
        all_combs = all_combs[::step]

    best_sharpe = -999
    best_params = None
    best_result = None
    scan_results = []

    for comb in all_combs:
        params = dict(zip(param_keys, comb))
        result = backtest_single(code, start, end, strategy_name, params, commission, slippage)
        if result and result["metrics"].get("夏普比率", -999) > -998:
            sharpe = result["metrics"]["夏普比率"]
            scan_results.append({
                **params,
                "夏普比率": sharpe,
                "年化收益率%": result["metrics"].get("年化收益率%", 0),
                "最大回撤%": result["metrics"].get("最大回撤%", 0),
                "胜率%": result["metrics"].get("胜率%", 0),
                "总收益率%": result["metrics"].get("总收益率%", 0),
            })
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_params = params
                best_result = result

    return {
        "best_params": best_params,
        "best_metrics": best_result["metrics"] if best_result else None,
        "best_sharpe": best_sharpe,
        "scan_results": pd.DataFrame(scan_results) if scan_results else pd.DataFrame(),
        "total_combs": len(all_combs),
    }


def multi_strategy_comparison(code, start, end, commission=0.03, slippage=0.05):
    """多策略同时对比"""
    results = {}
    for sname, sinfo in STRATEGIES.items():
        # 使用默认参数
        default_params = {k: v[0] for k, v in sinfo["params"].items()}
        result = backtest_single(code, start, end, sname, default_params, commission, slippage)
        if result:
            results[sname] = result
    return results