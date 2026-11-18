"""
StockPulse 预测/信号引擎 — 技术信号汇总 + 涨跌概率 + 量价背离 + 历史回测

2026-11-02 新增。在现有技术指标(indicators)基础上构建：
- 技术信号汇总：MA金叉死叉 / MACD / RSI超买卖 / KDJ / BOLL突破 / 量价背离 / 连阳连阴
- 涨跌概率估算：多因子打分模型（MA趋势/MACD/RSI/动量/相对强弱）→ 归一化 0-100%
- 量价背离预警：顶背离(价新高量萎缩) / 底背离(价新低但主力流入)
- 历史信号回测：对指定信号扫描历史，统计其后 5/10/20 日胜率与平均收益

数据通道：SpDataService.query_raw（PG 优先）。
"""
from typing import Optional

from ..data_service import SpDataService
from ....utils.indicators import calc_ma, calc_macd, calc_rsi, calc_kdj, calc_boll


def _safe_float(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _resolve_date(date: Optional[str]) -> str:
    """交易日 YYYYMMDD（默认最新交易日）。"""
    if date:
        return date.replace("-", "")
    d = SpDataService.query_raw(
        "daily", "SELECT DISTINCT trade_date FROM daily ORDER BY trade_date DESC LIMIT 1")
    if d.empty:
        return ""
    d0 = str(d.iloc[0]["trade_date"])
    return d0.replace("-", "") if "-" in d0 else d0


def _load_daily(ts_code: str, date: str, limit: int = 180):
    """加载个股日线（升序，含量）。"""
    d = SpDataService.query_raw(
        "daily",
        "SELECT trade_date, open, high, low, close, pre_close, pct_chg, vol, amount "
        "FROM daily WHERE ts_code=? AND trade_date<=? ORDER BY trade_date ASC LIMIT ?",
        [ts_code, date, limit])
    return d


# ── 放量突破临界点（陈江挺） ─────────────────────────────
def _detect_breakout(d, close, lookback_n: int = 20, vol_factor: float = 1.5):
    """放量突破临界点：收盘价突破最近 lookback_n 日收盘价高点（关键阻力位），
    且当日成交量 >= vol_factor × 5日均量（成交量确认）。

    逻辑（陈江挺"临界点"理论）：
      - 突破关键阻力位 = 最小被证伪成本之入场点（错了止损近，对了有趋势空间）
      - 无成交量配合的突破视为无效信号。
    返回: 信号 dict 或 None。
    """
    if close is None or len(d) < lookback_n + 1:
        return None
    try:
        prior = d["close"].iloc[-(lookback_n + 1):-1]  # 不含当日的前 lookback_n 日
        hi = prior.max()
        if hi is None or hi <= 0:
            return None
        # 当日需突破前 high 且不在 20 日最高（排除极值日）
        if close > hi * 1.001:
            v5 = d["vol"].astype(float).tail(5).mean()
            cur_v = _safe_float(d["vol"].iloc[-1]) or 0
            if v5 > 0 and cur_v >= v5 * vol_factor:
                return {
                    "type": "放量突破临界点",
                    "level": "机会",
                    "detail": f"收盘{close:.2f}突破近{lookback_n}日高点{hi:.2f}，"
                              f"量{cur_v/1e4:.0f}万手 = {cur_v/v5:.1f}倍5日均量（成交量确认）",
                }
    except Exception:
        return None
    return None


# ── 技术信号识别 ──────────────────────────────────────────
def analyze_signals(ts_code: str, date: Optional[str] = None):
    """技术信号汇总。返回 (signals, indicators_snapshot, price_ctx)。"""
    date = _resolve_date(date)
    d = _load_daily(ts_code, date)
    if d.empty or len(d) < 30:
        return [], {}, None

    try:
        d = calc_all_for_analysis(d)
    except Exception:
        pass

    last = d.iloc[-1]
    prev = d.iloc[-2] if len(d) >= 2 else last
    close = _safe_float(last["close"])
    signals = []

    # MA 金叉 / 死叉
    for fast, slow in (("MA5", "MA10"), ("MA5", "MA20"), ("MA10", "MA20")):
        if (fast in d.columns and slow in d.columns
                and not d[fast].isna().iloc[-1] and not d[slow].isna().iloc[-1]
                and not d[fast].isna().iloc[-2] and not d[slow].isna().iloc[-2]):
            cross_up = d[fast].iloc[-2] <= d[slow].iloc[-2] and d[fast].iloc[-1] > d[slow].iloc[-1]
            cross_dn = d[fast].iloc[-2] >= d[slow].iloc[-2] and d[fast].iloc[-1] < d[slow].iloc[-1]
            # 仅记录 MA5/MA10（主信号）
            if (fast, slow) == ("MA5", "MA10"):
                if cross_up:
                    signals.append({"type": "MA金叉", "level": "多头", "detail": "MA5上穿MA10"})
                elif cross_dn:
                    signals.append({"type": "MA死叉", "level": "空头", "detail": "MA5下穿MA10"})

    # MACD 金叉/死叉
    if "MACD_DIF" in d.columns and not d["MACD_DIF"].iloc[-2:].isna().any():
        dif_up = d["MACD_DIF"].iloc[-2] <= d["MACD_DEA"].iloc[-2] and d["MACD_DIF"].iloc[-1] > d["MACD_DEA"].iloc[-1]
        dif_dn = d["MACD_DIF"].iloc[-2] >= d["MACD_DEA"].iloc[-2] and d["MACD_DIF"].iloc[-1] < d["MACD_DEA"].iloc[-1]
        if dif_up:
            signals.append({"type": "MACD金叉", "level": "多头", "detail": "DIF上穿DEA"})
        elif dif_dn:
            signals.append({"type": "MACD死叉", "level": "空头", "detail": "DIF下穿DEA"})

    # RSI 超买超卖
    if "RSI14" in d.columns and not d["RSI14"].isna().iloc[-1]:
        rsi = _safe_float(last["RSI14"])
        if rsi is not None:
            if rsi > 70:
                signals.append({"type": "RSI超买", "level": "风险", "detail": f"RSI14={rsi:.0f}>70"})
            elif rsi < 30:
                signals.append({"type": "RSI超卖", "level": "机会", "detail": f"RSI14={rsi:.0f}<30"})

    # KDJ 金叉/超买超卖
    if "KDJ_K" in d.columns and not d["KDJ_K"].iloc[-2:].isna().any():
        k_up = d["KDJ_K"].iloc[-2] <= d["KDJ_D"].iloc[-2] and d["KDJ_K"].iloc[-1] > d["KDJ_D"].iloc[-1]
        if k_up:
            signals.append({"type": "KDJ金叉", "level": "多头", "detail": "K线上穿D线"})
        elif _safe_float(last["KDJ_J"]) and _safe_float(last["KDJ_J"]) > 100:
            signals.append({"type": "KDJ超买", "level": "风险", "detail": f"J值={_safe_float(last['KDJ_J']):.0f}"})

    # BOLL 突破
    if "BOLL_UP" in d.columns and not d["BOLL_UP"].isna().iloc[-1]:
        if close is not None:
            if close > _safe_float(last["BOLL_UP"]):
                signals.append({"type": "BOLL上轨突破", "level": "走强", "detail": "收盘价站上布林上轨"})
            elif close < _safe_float(last["BOLL_DN"]):
                signals.append({"type": "BOLL下轨跌破", "level": "走弱", "detail": "收盘价跌破布林下轨"})

    # 放量突破临界点（陈江挺：突破关键阻力位 + 成交量确认；被证伪成本最小）
    bo = _detect_breakout(d, close)
    if bo:
        signals.append(bo)

    # 连阳/连阴
    cnt = 0
    for i in range(len(d) - 1, max(0, len(d) - 6) - 1, -1):
        if _safe_float(d.iloc[i]["pct_chg"]) and _safe_float(d.iloc[i]["pct_chg"]) > 0:
            cnt += 1
        else:
            break
    if cnt >= 3:
        signals.append({"type": f"{cnt}连阳", "level": "动能", "detail": f"连续{cnt}日收阳"})
    cnt = 0
    for i in range(len(d) - 1, max(0, len(d) - 6) - 1, -1):
        if _safe_float(d.iloc[i]["pct_chg"]) and _safe_float(d.iloc[i]["pct_chg"]) < 0:
            cnt += 1
        else:
            break
    if cnt >= 3:
        signals.append({"type": f"{cnt}连阴", "level": "弱势", "detail": f"连续{cnt}日收阴"})

    # 量价背离快检（顶背离：价新高量萎缩）
    if len(d) >= 20:
        try:
            hi20 = d["close"].tail(20).max()
            if close is not None and close >= hi20 * 0.99:
                v5 = d["vol"].astype(float).tail(5).mean()
                v20 = d["vol"].astype(float).tail(20).mean()
                if v20 > 0 and v5 < v20 * 0.8:
                    signals.append({"type": "量价顶背离", "level": "风险", "detail": "价近20日新高但量能萎缩"})
        except Exception:
            pass

    # 指标快照
    snapshot = {}
    for k in ("close", "pct_chg", "vol", "MA5", "MA10", "MA20", "MA60",
              "MACD_DIF", "MACD_DEA", "MACD_HIST", "RSI14", "KDJ_K", "KDJ_D", "KDJ_J",
              "BOLL_UP", "BOLL_DN", "BOLL_MID"):
        if k in d.columns and not d[k].isna().iloc[-1]:
            v = d[k].iloc[-1]
            snapshot[k] = round(float(v), 4) if isinstance(v, (int, float)) else str(v)

    return signals, snapshot, {"close": close, "trade_date": str(d.iloc[-1]["trade_date"]).replace("-", "")}


def calc_all_for_analysis(d):
    """为信号分析补齐全部指标。"""
    d = d.reset_index(drop=True)
    d = calc_ma(d)
    if len(d) >= 26:
        d = calc_macd(d)
    if len(d) >= 6:
        d = calc_rsi(d, periods=(14,))
    if len(d) >= 9:
        d = calc_kdj(d)
        d = calc_boll(d)
    return d


# ── 涨跌概率估算（多因子打分模型） ──────────────────────
def predict_probability(ts_code: str, date: Optional[str] = None):
    """估算未来 5-20 日看涨概率（0-100%）。多因子打分，透明归因。"""
    date = _resolve_date(date)
    d = _load_daily(ts_code, date, 180)
    if len(d) < 60:
        return {"ts_code": ts_code, "probability": None, "error": "样本不足(需>=60日)"}

    try:
        d = calc_all_for_analysis(d)
    except Exception:
        pass

    last = d.iloc[-1]
    close = _safe_float(last["close"])
    score = 0.0  # 加权平均各因子贡献（每因子 ~50 中性），不再加基础50避免双重计数
    wsum = 0.0   # 实际应用到的权重和（因子缺失时 <1，用于归一化）
    factors = []

    # 均线趋势（权重高）
    if "MA20" in d.columns and not d["MA20"].isna().iloc[-1] \
            and not d["MA60"].isna().iloc[-1]:
        ma20, ma60 = _safe_float(last["MA20"]), _safe_float(last["MA60"])
        if close is not None and ma20 is not None and ma60 is not None:
            trend = (close / ma20 - 1) * 100
            f = 50 + trend * 2
            score += f * 0.25
            wsum += 0.25
            factors.append({"factor": "均线趋势", "value": trend, "contrib": round(f, 1)})

    # MACD（归一化为相对收盘价的百分比，避免高价股 hist 绝对值过大导致饱和）
    if "MACD_HIST" in d.columns and not d["MACD_HIST"].iloc[-1] is None:
        hist = _safe_float(last["MACD_HIST"])
        if hist and close and close > 0:
            hist_pct = hist / close * 100  # 相对价格百分比
            f = 50 + max(-30, min(30, hist_pct * 8))
            score += f * 0.2
            wsum += 0.2
            factors.append({"factor": "MACD动能", "value": round(hist_pct, 2), "contrib": round(f, 1)})

    # RSI
    if "RSI14" in d.columns and not d["RSI14"].isna().iloc[-1]:
        rsi = _safe_float(last["RSI14"])
        # RSI 越接近 50 越中性，>60 略偏多，<40 略偏空，极端反向
        if rsi is not None:
            if 45 <= rsi <= 55:
                f = 50
            elif 55 < rsi <= 70:
                f = 50 + (rsi - 55)
            elif rsi > 70:
                f = 60 - (rsi - 70) * 2  # 超买回落
            elif 30 <= rsi < 45:
                f = 50 - (45 - rsi)
            else:
                f = 40 + (30 - rsi)  # 超卖反弹
            score += f * 0.15
            wsum += 0.15
            factors.append({"factor": "RSI位置", "value": round(rsi, 1), "contrib": round(f, 1)})

    # 动量（近20日涨幅）
    if len(d) >= 20:
        c20 = _safe_float(d["close"].iloc[-20])
        if close is not None and c20 and c20 > 0:
            mom = (close / c20 - 1) * 100
            f = 50 + mom * 0.8
            score += f * 0.2
            wsum += 0.2
            factors.append({"factor": "20日动量", "value": round(mom, 1), "contrib": round(f, 1)})

    # 量能配合
    if len(d) >= 20 and close is not None:
        try:
            v5 = d["vol"].astype(float).tail(5).mean()
            v20 = d["vol"].astype(float).tail(20).mean()
            # 温和放量(1.2-1.8)最健康
            if v20 > 0:
                vr = v5 / v20
                if 1.2 <= vr <= 1.8:
                    f = 60
                elif vr > 1.8:
                    f = 45  # 过热
                elif vr < 0.7:
                    f = 40  # 缩量
                else:
                    f = 52
                score += f * 0.2
                wsum += 0.2
                factors.append({"factor": "量能配合", "value": round(vr, 2), "contrib": round(f, 1)})
        except Exception:
            pass

    # 按实际应用权重归一化，缺因子时不整体拉低
    if wsum > 0:
        score = score / wsum
    prob = round(max(5, min(95, score)), 1)
    return {
        "ts_code": ts_code,
        "trade_date": date,
        "probability": prob,  # 看涨概率 %
        "horizon_hint": "未来5-20个交易日方向倾向",
        "factors": factors,
    }


# ── 量价背离预警 ──────────────────────────────────────────
def detect_divergence(ts_code: str, date: Optional[str] = None):
    """量价背离预警。顶背离(价新高量萎缩) / 底背离(价新低但资金流入/量增)。"""
    date = _resolve_date(date)
    d = _load_daily(ts_code, date, 120)
    if len(d) < 60:
        return {"ts_code": ts_code, "trade_date": date, "divergences": []}

    divergences = []
    close = _safe_float(d["close"].iloc[-1])

    # 顶背离：近20日价高点 vs 对应量能
    if close is not None:
        w = d.tail(20)
        w = w.reset_index(drop=True)
        hi_idx = w["close"].idxmax()
        hi_price = _safe_float(w.loc[hi_idx, "close"])
        hi_vol = _safe_float(w.loc[hi_idx, "vol"])
        # 当前价接近20日高点
        if hi_idx < len(w) - 1 and hi_price and hi_vol:
            if close >= hi_price * 0.98:
                cur_vol = _safe_float(w["vol"].iloc[-1]) or 0
                if cur_vol < hi_vol * 0.6:
                    divergences.append({
                        "type": "顶背离",
                        "level": "风险",
                        "detail": f"价格逼近20日高点({close:.2f})但最新量({cur_vol/1e6:.1f}万手)远低于前高量({hi_vol/1e6:.1f}万手)，上涨动能存疑",
                    })

    # 底背离：价格创新低但主力净流入（资金底背离）
    try:
        lo20 = _safe_float(d["low"].tail(20).min())
        mf = SpDataService.query_raw(
            "moneyflow",
            "SELECT trade_date, net_mf_amount FROM moneyflow "
            "WHERE ts_code=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 5",
            [ts_code, date])
        if not mf.empty and lo20 is not None and close is not None and close <= lo20 * 1.02:
            net = mf["net_mf_amount"].apply(_safe_float).sum() or 0
            if net > 0:
                divergences.append({
                    "type": "底背离(资金)",
                    "level": "机会",
                    "detail": f"价格创20日低位({close:.2f})但近5日主力净流入 {net/100000:.2f}亿，资金低位吸筹",
                })
    except Exception:
        pass

    return {"ts_code": ts_code, "trade_date": date, "divergences": divergences}


# ── 历史信号回测 ──────────────────────────────────────────
def backtest_signal(ts_code: str, signal: str = "MACD金叉", lookback: int = 500,
                    horizon: int = 10):
    """对指定信号做历史回测：统计信号出现后 horizon 日胜率与平均收益。

    signal 可选: MACD金叉 / MACD死叉 / MA金叉 / MA死叉 / RSI超卖(<=30) / RSI超买(>=70)
    / 放量突破(收盘破20日高点+量>=1.5×5日均量, 陈江挺临界点)
    """
    date = _resolve_date(None)
    if not date:
        return {"ts_code": ts_code, "signal": signal, "error": "无交易日数据"}
    d = _load_daily(ts_code, date, lookback)
    if len(d) < 60:
        return {"ts_code": ts_code, "signal": signal, "error": "样本不足"}

    try:
        d = calc_all_for_analysis(d)
    except Exception:
        pass

    results = []
    close_list = d["close"].tolist()
    vol_list = d["vol"].tolist() if "vol" in d.columns else [None] * len(d)

    def _close(i):
        return _safe_float(close_list[i])

    for i in range(1, len(d) - horizon):
        hit = False
        # 信号判定（需前一交易日对比）
        prev, cur = i - 1, i
        if signal == "MACD金叉":
            if "MACD_DIF" in d.columns and not d["MACD_DIF"].isna().iloc[cur]:
                hit = (d["MACD_DIF"].iloc[prev] <= d["MACD_DEA"].iloc[prev]
                       and d["MACD_DIF"].iloc[cur] > d["MACD_DEA"].iloc[cur])
        elif signal == "MACD死叉":
            if "MACD_DIF" in d.columns and not d["MACD_DIF"].isna().iloc[cur]:
                hit = (d["MACD_DIF"].iloc[prev] >= d["MACD_DEA"].iloc[prev]
                       and d["MACD_DIF"].iloc[cur] < d["MACD_DEA"].iloc[cur])
        elif signal == "MA金叉":
            if "MA5" in d.columns and not d["MA5"].isna().iloc[cur]:
                hit = (d["MA5"].iloc[prev] <= d["MA20"].iloc[prev]
                       and d["MA5"].iloc[cur] > d["MA20"].iloc[cur])
        elif signal == "MA死叉":
            if "MA5" in d.columns and not d["MA5"].isna().iloc[cur]:
                hit = (d["MA5"].iloc[prev] >= d["MA20"].iloc[prev]
                       and d["MA5"].iloc[cur] < d["MA20"].iloc[cur])
        elif signal == "RSI超卖":
            if "RSI14" in d.columns and not d["RSI14"].isna().iloc[cur]:
                hit = _safe_float(d["RSI14"].iloc[cur]) is not None and d["RSI14"].iloc[cur] <= 30
        elif signal == "RSI超买":
            if "RSI14" in d.columns and not d["RSI14"].isna().iloc[cur]:
                hit = _safe_float(d["RSI14"].iloc[cur]) is not None and d["RSI14"].iloc[cur] >= 70
        elif signal in ("放量突破", "放量突破临界点"):
            # 收盘突破此前20日高点 + 量>=1.5×5日均量（成交量确认）
            if cur >= 21:
                prior = d["close"].iloc[cur - 20:cur]
                hi = prior.max()
                c_cur = _close(cur)
                if hi and c_cur and hi > 0 and c_cur > hi * 1.001:
                    v5 = d["vol"].astype(float).iloc[cur - 5:cur].mean()
                    v_cur = _safe_float(d["vol"].iloc[cur]) or 0
                    hit = v5 > 0 and v_cur >= v5 * 1.5
        if hit:
            buy = _close(cur)
            if buy and buy > 0 and _close(cur + horizon) is not None:
                ret = (_close(cur + horizon) / buy - 1) * 100
                results.append({"date": str(d["trade_date"].iloc[cur]).replace("-", ""),
                                "ret": round(ret, 2)})

    if not results:
        return {"ts_code": ts_code, "signal": signal, "lookback": lookback,
                "horizon": horizon, "count": 0, "message": "样本期无该信号"}

    wins = [r for r in results if r["ret"] > 0]
    avg_ret = sum(r["ret"] for r in results) / len(results)
    return {
        "ts_code": ts_code,
        "signal": signal,
        "lookback": lookback,
        "horizon": horizon,
        "count": len(results),
        "win_rate": round(len(wins) / len(results) * 100, 1),
        "avg_return": round(avg_ret, 2),
        "best": round(max(r["ret"] for r in results), 2),
        "worst": round(min(r["ret"] for r in results), 2),
        "recent": results[-10:][::-1],  # 最近10次
    }
