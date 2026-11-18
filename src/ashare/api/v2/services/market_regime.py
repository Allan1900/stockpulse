"""
StockPulse 市场状态引擎 —「大市开关」Market Regime

2026-11-02 新增。源自陈江挺《炒股的智慧》"大市不好不买"与
"200日均线=长期牛熊分界 / 60日均线=中期生命线"的趋势状态框架：

    - 价格在 MA200 上方 → 长期做多环境；下方 → 观望/现金
    - 价格在 MA60 上方 → 中期趋势向上；下方 → 中期偏空
    - 综合为市场状态： 可操作(多头) / 观望(空头) / 震荡(方向不明)

设计要点：
    - 用「事后的、可观察的趋势状态」替代「事前的、不可靠的预测」
      —— 只报告当前环境是否允许出手，不做涨跌预测。
    - 输出带置信度（基于 MA 计算所需的日线覆盖度）。
    - 供 /diagnosis、/signal、/discipline 等引擎作为"环境门"调用
      （大市空头时，个股信号/诊股结果应标注环境不允许）。

数据通道：SpDataService.query_raw → PG index_daily（上证 000001.SH，
2015 至今 2871 交易日可用）。

适用边界（不越界）：本引擎回答"大市当前是否处于可操作状态"，
不回答"后市涨跌"也不做价值判断。
"""
from typing import Optional

from ..data_service import SpDataService

DEFAULT_INDEX = "000001.SH"  # 上证指数
_MA_LONG = 200  # 长期牛熊分界
_MA_MID = 60    # 中期生命线


def _safe_float(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _latest_date() -> str:
    d = SpDataService.query_raw(
        "index_daily",
        "SELECT DISTINCT trade_date FROM index_daily ORDER BY trade_date DESC LIMIT 1")
    if d.empty:
        return ""
    d0 = str(d.iloc[0]["trade_date"])
    return d0.replace("-", "") if "-" in d0 else d0


def get_market_regime(ts_code: str = DEFAULT_INDEX,
                      date: Optional[str] = None) -> dict:
    """
    计算大盘市场状态。返回结构化字典（非 sp_success 包装，供 route 层包装）。

    返回字段：
        ts_code / trade_date / close / ma200 / ma60
        状态组合:
            mkt_state   : 可操作(多头) | 观望(空头) | 震荡
            long_bull   : 价格在 MA200 上方（长期牛熊）True/False
            mid_bull    : 价格在 MA60 上方（中期方向） True/False
            ma_trend    : 均线排列 多头排列/空头排列/纠缠
        confidence    : 高(需≥MA200日线) / 中(需≥MA60) / 低(数据不足)
        note          : 一句话结论
    """
    if date:
        date = date.replace("-", "")
    else:
        date = _latest_date()

    # 取 MA200 所需的历史日线（多取 20 冗余）
    rows = SpDataService.query_raw(
        "index_daily",
        "SELECT trade_date, close FROM index_daily "
        "WHERE ts_code=? AND trade_date<=? ORDER BY trade_date DESC LIMIT ?",
        [ts_code, date, _MA_LONG + 20])
    if rows.empty:
        return {
            "ts_code": ts_code, "trade_date": date,
            "error": "无指数日线数据", "confidence": "低",
        }

    df = rows.sort_values("trade_date").reset_index(drop=True)
    latest = df.iloc[-1]
    close = _safe_float(latest["close"])
    closes = [c for c in (_safe_float(x) for x in df["close"]) if c is not None]
    n = len(closes)
    if n < _MA_MID or close is None:
        return {
            "ts_code": ts_code, "trade_date": str(latest["trade_date"]),
            "close": close, "mkt_state": "震荡", "confidence": "低",
            "note": "日线数据不足，无法判断市场状态",
        }

    ma60 = sum(closes[-_MA_MID:]) / _MA_MID
    if n >= _MA_LONG + 1:
        ma200 = sum(closes[-(_MA_LONG + 1):-1]) / _MA_LONG  # 不含今日，昨日 MA200
        confidence = "高"
    elif n >= _MA_MID + 1:
        # 数据不足以算 MA200，用现有数据近似（标注低置信度）
        ma200 = sum(closes) / n
        confidence = "低"
    else:
        ma200 = None
        confidence = "低"

    long_bull = close > ma200 if ma200 else None
    mid_bull = close > ma60

    # 均线排列趋势（用最近 MA20 与 MA60 关系补充）
    ma20 = sum(closes[-20:]) / 20 if n >= 20 else None
    if ma20 is not None:
        if ma20 > ma60 and close > ma20:
            ma_trend = "多头排列"
        elif ma20 < ma60 and close < ma20:
            ma_trend = "空头排列"
        else:
            ma_trend = "纠缠"
    else:
        ma_trend = "未知"

    # 综合市场状态
    if long_bull is True and mid_bull:
        mkt_state = "可操作(多头)"
    elif long_bull is False and (not mid_bull):
        mkt_state = "观望(空头)"
    elif long_bull is True and not mid_bull:
        mkt_state = "震荡(长期多/中期空)"
    elif long_bull is False and mid_bull:
        mkt_state = "震荡(长期空/中期多)"
    else:
        mkt_state = "震荡"

    # 结论措辞（陈江挺式：跟随环境，不预测）
    if mkt_state == "可操作(多头)":
        note = "大盘处于长期多头 + 中期向上环境，允许出手（陈江挺'上涨趋势中买股票'）"
    elif mkt_state == "观望(空头)":
        note = "大盘处于空头环境，安坐不动，最好什么都别买（大市不好不买）"
    else:
        note = "大盘方向不明或长中周期背离，轻仓观望，等待趋势一致"

    return {
        "ts_code": ts_code,
        "trade_date": str(latest["trade_date"]),
        "close": round(close, 2),
        "ma200": round(ma200, 2) if ma200 else None,
        "ma60": round(ma60, 2),
        "ma20": round(ma20, 2) if ma20 else None,
        "long_bull": long_bull,
        "mid_bull": mid_bull,
        "ma_trend": ma_trend,
        "mkt_state": mkt_state,
        "confidence": confidence,
        "note": note,
        # 框架标识（启用提示）
        "framework": {
            "name": "陈江挺《炒股的智慧》趋势状态框架",
            "enabled": True,
            "usage": "本状态为执行纪律层 L1 环境门：回答『大市是否允许出手』，不做涨跌预测与公司价值判断。",
        },
    }


# 供其他引擎当作"环境门"调用的浅封装：市场是否允许出手
def market_allows_trading(date: Optional[str] = None,
                          ts_code: str = DEFAULT_INDEX) -> bool:
    r = get_market_regime(ts_code, date)
    return r.get("mkt_state", "").startswith("可操作")


if __name__ == "__main__":
    import json
    print(json.dumps(get_market_regime(), ensure_ascii=False, indent=2))
