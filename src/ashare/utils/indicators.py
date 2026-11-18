"""
技术指标计算模块 — 纯 Python 实现，无需 TA-Lib
支持: MA, MACD, RSI, KDJ, BOLL
"""
import pandas as pd
import numpy as np


def calc_ma(df, periods=(5, 10, 20, 60), price_col="close"):
    """均线"""
    for p in periods:
        df[f"MA{p}"] = df[price_col].rolling(window=p).mean()
    return df


def calc_macd(df, fast=12, slow=26, signal=9, price_col="close"):
    """MACD 指标"""
    ema_fast = df[price_col].ewm(span=fast, adjust=False).mean()
    ema_slow = df[price_col].ewm(span=slow, adjust=False).mean()
    df["MACD_DIF"] = ema_fast - ema_slow
    df["MACD_DEA"] = df["MACD_DIF"].ewm(span=signal, adjust=False).mean()
    df["MACD_HIST"] = 2 * (df["MACD_DIF"] - df["MACD_DEA"])
    return df


def calc_rsi(df, periods=(6, 12, 24), price_col="close"):
    """RSI 指标"""
    delta = df[price_col].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    for p in periods:
        avg_gain = gain.rolling(window=p, min_periods=1).mean()
        avg_loss = loss.rolling(window=p, min_periods=1).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        df[f"RSI{p}"] = 100 - (100 / (1 + rs))
    return df


def calc_kdj(df, n=9, m1=3, m2=3):
    """KDJ 指标"""
    low_n = df["low"].rolling(window=n).min()
    high_n = df["high"].rolling(window=n).max()
    rsv = (df["close"] - low_n) / (high_n - low_n).replace(0, np.nan) * 100
    df["KDJ_K"] = rsv.ewm(com=m1 - 1, adjust=False).mean()
    df["KDJ_D"] = df["KDJ_K"].ewm(com=m2 - 1, adjust=False).mean()
    df["KDJ_J"] = 3 * df["KDJ_K"] - 2 * df["KDJ_D"]
    return df


def calc_boll(df, period=20, std=2, price_col="close"):
    """布林带"""
    df["BOLL_MID"] = df[price_col].rolling(window=period).mean()
    df["BOLL_STD"] = df[price_col].rolling(window=period).std()
    df["BOLL_UP"] = df["BOLL_MID"] + std * df["BOLL_STD"]
    df["BOLL_DN"] = df["BOLL_MID"] - std * df["BOLL_STD"]
    df["BOLL_WIDTH"] = df["BOLL_UP"] - df["BOLL_DN"]
    df["BOLL_POS"] = (df[price_col] - df["BOLL_DN"]) / df["BOLL_WIDTH"].replace(0, np.nan)
    return df


def calc_all_indicators(df):
    """一键计算所有常用指标"""
    df = df.copy()
    if len(df) < 5:
        return df
    df = calc_ma(df)
    if len(df) >= 26:
        df = calc_macd(df)
    if len(df) >= 6:
        df = calc_rsi(df)
    if len(df) >= 9:
        df = calc_kdj(df)
        df = calc_boll(df)
    return df


def calc_correlation(returns_df):
    """计算多只股票收益率相关系数矩阵"""
    return returns_df.corr()


def calc_relative_strength(stock_close, bench_close):
    """相对强弱 (RS 线)"""
    return stock_close / bench_close * 100