"""
技术指标计算模块 — 纯 Python 实现，无需 TA-Lib

支持: MA, MACD, RSI, KDJ, BOLL
"""
import pandas as pd
import numpy as np


def calc_ma(df, periods=[5, 10, 20, 60], price_col="close"):
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


def calc_rsi(df, periods=[6, 12, 24], price_col="close"):
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
    df["KDJ_K"] = rsv.ewm(com=m1-1, adjust=False).mean()
    df["KDJ_D"] = df["KDJ_K"].ewm(com=m2-1, adjust=False).mean()
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


def calc_obv(df, price_col="close", vol_col="vol"):
    """OBV (On-Balance Volume) 量能指标"""
    df = df.copy()
    df["OBV"] = (np.sign(df[price_col].diff()) * df[vol_col]).fillna(0).cumsum()
    df["OBV_MA5"] = df["OBV"].rolling(window=5).mean()
    df["OBV_MA10"] = df["OBV"].rolling(window=10).mean()
    return df


def calc_vwap(df):
    """VWAP (Volume-Weighted Average Price) 日内均价近似"""
    df = df.copy()
    # 日线场景: VWAP ≈ (close * vol) / vol 的滚动加权
    if "amount" in df.columns and "vol" in df.columns:
        df["VWAP"] = (df["amount"] * 1000) / df["vol"]  # amount千元→元, vol手→股
    return df


# ── 高级指标：ADX / CCI / Williams %R ──────────────────────────────

def calc_adx(df, period=14):
    """ADX (Average Directional Index) + DI+/DI- 趋势强度指标"""
    df = df.copy()
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)

    # True Range
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["ATR"] = tr.ewm(span=period, adjust=False).mean()

    # ±DM
    up_move = high - high.shift(1)
    dn_move = low.shift(1) - low
    df["+DM"] = np.where((up_move > dn_move) & (up_move > 0), up_move, 0.0)
    df["-DM"] = np.where((dn_move > up_move) & (dn_move > 0), dn_move, 0.0)

    sm_plus = df["+DM"].ewm(span=period, adjust=False).mean()
    sm_minus = df["-DM"].ewm(span=period, adjust=False).mean()

    df["+DI"] = 100 * sm_plus / df["ATR"].replace(0, np.nan)
    df["-DI"] = 100 * sm_minus / df["ATR"].replace(0, np.nan)

    dx = 100 * (df["+DI"] - df["-DI"]).abs() / (df["+DI"] + df["-DI"]).replace(0, np.nan)
    df["ADX"] = dx.ewm(span=period, adjust=False).mean()
    return df


def calc_cci(df, period=20):
    """CCI (Commodity Channel Index) 顺势指标"""
    df = df.copy()
    tp = (df["high"] + df["low"] + df["close"]) / 3
    sma_tp = tp.rolling(window=period).mean()
    md = tp.rolling(window=period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    df["CCI"] = (tp - sma_tp) / (0.015 * md.replace(0, np.nan))
    return df


def calc_williams_r(df, period=14):
    """Williams %R (威廉指标)"""
    df = df.copy()
    hh = df["high"].rolling(window=period).max()
    ll = df["low"].rolling(window=period).min()
    df["WR"] = (hh - df["close"]) / (hh - ll).replace(0, np.nan) * -100
    return df


# ── 高级指标信号检测 ────────────────────────────────────

def eval_adx_signal(df):
    """ADX 趋势强度判断"""
    if "ADX" not in df.columns or len(df) < 2:
        return {}
    d = df.iloc[-1]
    adx = d["ADX"]
    plus_di, minus_di = d.get("+DI"), d.get("-DI")
    if pd.isna(adx):
        return {}
    if adx >= 50:
        strength = "🔥 极强趋势"
    elif adx >= 35:
        strength = "⚡ 强趋势"
    elif adx >= 25:
        strength = "📊 中等趋势"
    elif adx >= 20:
        strength = "📈 趋势萌芽"
    else:
        strength = "🔀 盘整/无趋势"

    if pd.notna(plus_di) and pd.notna(minus_di):
        direction = "多头 ↑" if plus_di > minus_di else "空头 ↓"
    else:
        direction = ""
    return {"ADX": adx, "+DI": plus_di, "-DI": minus_di,
            "strength": strength, "direction": direction}


def eval_cci_signal(df):
    """CCI 超买超卖信号"""
    if "CCI" not in df.columns:
        return {}
    cci = df.iloc[-1]["CCI"]
    if pd.isna(cci):
        return {}
    if cci >= 200:
        tag = "⚠️ 严重超买"
    elif cci >= 150:
        tag = "⚠️ 超买"
    elif cci >= 100:
        tag = "📈 偏强 (突破+100)"
    elif cci <= -200:
        tag = "✅ 严重超卖"
    elif cci <= -150:
        tag = "✅ 超卖"
    elif cci <= -100:
        tag = "📉 偏弱 (跌破-100)"
    else:
        tag = "正常"
    return {"CCI": cci, "signal": tag}


def eval_wr_signal(df):
    """Williams %R 超买超卖信号"""
    if "WR" not in df.columns:
        return {}
    wr = df.iloc[-1]["WR"]
    if pd.isna(wr):
        return {}
    if wr <= -80:
        tag = "✅ 超卖 (<= -80)"
    elif wr <= -50:
        tag = "偏弱"
    elif wr <= -20:
        tag = "偏强"
    else:
        tag = "⚠️ 超买 (> -20)"
    return {"WR": wr, "signal": tag}


# ── 聚合 ────────────────────────────────────────────────

def calc_all_indicators(df):
    """一键计算所有常用指标（基础 + 高级）"""
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
        df = calc_obv(df)
    if len(df) >= 30:
        df = calc_adx(df)
        df = calc_cci(df)
        df = calc_williams_r(df)
    return df


def eval_all_signals(df):
    """聚合所有指标信号（基础 + 高级）"""
    s = {
        "macd": eval_macd_signal(df),
        "rsi": eval_rsi_signal(df),
        "kdj": eval_kdj_signal(df),
        "boll": eval_boll_signal(df),
        "obv": eval_obv_signal(df),
    }
    if "ADX" in df.columns:
        s["adx"] = eval_adx_signal(df)
    if "CCI" in df.columns:
        s["cci"] = eval_cci_signal(df)
    if "WR" in df.columns:
        s["wr"] = eval_wr_signal(df)
    return s


def eval_macd_signal(df):
    """MACD 信号检测: 返回最新信号状态"""
    if "MACD_DIF" not in df.columns or len(df) < 2:
        return {}
    d = df.iloc[-1]
    prev = df.iloc[-2]
    signal = "中性"
    if pd.isna(d["MACD_DIF"]) or pd.isna(d["MACD_DEA"]):
        return {}
    if prev["MACD_DIF"] <= prev["MACD_DEA"] and d["MACD_DIF"] > d["MACD_DEA"]:
        signal = "🔴 金叉 ↑"
    elif prev["MACD_DIF"] >= prev["MACD_DEA"] and d["MACD_DIF"] < d["MACD_DEA"]:
        signal = "🟢 死叉 ↓"
    elif d["MACD_DIF"] > d["MACD_DEA"]:
        signal = "🔺 DIF > DEA (多头)"
    else:
        signal = "🔻 DIF < DEA (空头)"
    return {
        "DIF": d["MACD_DIF"], "DEA": d["MACD_DEA"],
        "HIST": d["MACD_HIST"], "signal": signal
    }


def eval_rsi_signal(df):
    """RSI 超买超卖信号"""
    if "RSI6" not in df.columns:
        return {}
    d = df.iloc[-1]
    signals = {}
    for p in ["6", "12", "24"]:
        col = f"RSI{p}"
        val = d[col]
        if pd.isna(val):
            continue
        if val >= 70:
            tag = "⚠️ 超买"
        elif val <= 30:
            tag = "✅ 超卖"
        else:
            tag = "正常"
        signals[col] = (float(f"{val:.1f}"), tag)
    return signals


def eval_kdj_signal(df):
    """KDJ 信号检测"""
    if "KDJ_K" not in df.columns or len(df) < 2:
        return {}
    d = df.iloc[-1]
    prev = df.iloc[-2]
    k, d_v, j = d["KDJ_K"], d["KDJ_D"], d["KDJ_J"]
    k_signal = "超买 ⚠️" if k >= 80 else ("超卖 ✅" if k <= 20 else "正常")
    if prev["KDJ_K"] <= prev["KDJ_D"] and k > d_v:
        cross_signal = "🔴 K金叉 ↑"
    elif prev["KDJ_K"] >= prev["KDJ_D"] and k < d_v:
        cross_signal = "🟢 K死叉 ↓"
    else:
        cross_signal = "无交叉"
    return {
        "K": k, "D": d_v, "J": j,
        "k_signal": k_signal,
        "cross": cross_signal
    }


def eval_boll_signal(df):
    """布林带位置和信号"""
    if "BOLL_UP" not in df.columns:
        return {}
    d = df.iloc[-1]
    close, up, mid, dn = d["close"], d["BOLL_UP"], d["BOLL_MID"], d["BOLL_DN"]
    if up == dn:
        return {}
    pos = (close - dn) / (up - dn) * 100
    if close >= up:
        zone = "⚠️ 突破上轨 (超买)"
    elif close <= dn:
        zone = "✅ 跌破下轨 (超卖)"
    elif close > mid:
        zone = "🔺 中轨上方 (偏强)"
    else:
        zone = "🔻 中轨下方 (偏弱)"
    return {
        "UP": up, "MID": mid, "DN": dn,
        "position": pos,
        "zone": zone,
        "width": up - dn
    }


def eval_obv_signal(df):
    """OBV 趋势判断"""
    if "OBV" not in df.columns or "OBV_MA5" not in df.columns or len(df) < 6:
        return {}
    d = df.iloc[-1]
    obv, ma5 = d["OBV"], d["OBV_MA5"]
    # OBV方向: 与5日均线比较
    if obv > ma5:
        trend = "📈 量能上行"
    elif obv < ma5:
        trend = "📉 量能下行"
    else:
        trend = "→ 量能平缓"

    # OBV与价格背离检测 (最近20日)
    p_chg = df["close"].pct_change().iloc[-20:].mean() if len(df) >= 20 else 0
    obv_chg = df["OBV"].pct_change().iloc[-20:].mean() if len(df) >= 20 else 0
    divergence = ""
    if p_chg > 0.01 and obv_chg < -0.01:
        divergence = "⚠️ 顶背离 (价涨量缩)"
    elif p_chg < -0.01 and obv_chg > 0.01:
        divergence = "✅ 底背离 (价跌量增)"

    return {
        "OBV": obv, "MA5": ma5,
        "trend": trend,
        "divergence": divergence,
        "obv_pct_chg_20d": obv_chg,
        "price_pct_chg_20d": p_chg
    }


def eval_all_signals(df):
    """聚合所有指标信号"""
    return {
        "macd": eval_macd_signal(df),
        "rsi": eval_rsi_signal(df),
        "kdj": eval_kdj_signal(df),
        "boll": eval_boll_signal(df),
        "obv": eval_obv_signal(df),
    }


def detect_macd_crosses(df, lookback=120):
    """检测最近 lookback 期内所有 MACD 金叉/死叉"""
    if "MACD_DIF" not in df.columns or len(df) < 3:
        return {"golden": [], "death": []}
    sub = df.tail(lookback).reset_index(drop=True)
    golden, death = [], []
    for i in range(1, len(sub)):
        prev = sub.iloc[i - 1]
        cur = sub.iloc[i]
        if pd.isna(prev["MACD_DIF"]) or pd.isna(prev["MACD_DEA"]):
            continue
        if prev["MACD_DIF"] <= prev["MACD_DEA"] and cur["MACD_DIF"] > cur["MACD_DEA"]:
            golden.append({"date": cur["trade_date"], "dif": cur["MACD_DIF"], "dea": cur["MACD_DEA"]})
        elif prev["MACD_DIF"] >= prev["MACD_DEA"] and cur["MACD_DIF"] < cur["MACD_DEA"]:
            death.append({"date": cur["trade_date"], "dif": cur["MACD_DIF"], "dea": cur["MACD_DEA"]})
    return {"golden": golden[-10:][::-1], "death": death[-10:][::-1]}


def calc_correlation(returns_df):
    """计算多只股票收益率相关系数矩阵"""
    return returns_df.corr()


def calc_relative_strength(stock_close, bench_close):
    """相对强弱 (RS 线)"""
    return stock_close / bench_close * 100
