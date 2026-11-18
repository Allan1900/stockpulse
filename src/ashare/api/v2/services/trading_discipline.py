"""
StockPulse 交易纪律引擎 — 陈江挺《炒股的智慧》执行纪律层

2026-11-02 新增。定位（严格限定——不越界）：
  本引擎回答"这笔交易（机会）值不值得参与、以多大风险、何时退出"，
  不回答"这家公司值多少钱"（后者由 diagnosis 财务维度 / 基本面数据负责）。

五层检查框架（源自研究提炼）：
  L1 环境过滤 : 大盘 MA200 牛熊 + MA60 方向 → 是否允许出手（"大市不好不买"）
  L2 标的/信号: 基本面初筛 + 趋势状态 + 临界点(放量突破)
  L3 风险预算 : 止损价(=跌破临界位或预设幅度) → 按单笔2%总资金反推仓位 → 组合敞口校验
  L4 退出管理 : 保本止损 / 跌破MA20退出线 / 量价背离预警
  L5 执行审计 : 计划 vs 执行偏差归因（系统成本 vs 纪律偏差）

哲学对应（内建于输出）：
  - Popper 证伪 : 环境不允许/止损逻辑不成立时，整单降级或不做
  - 置信度      : 基于维度覆盖度（高≥80% / 中≥50% / 低<50%）
  - 成败标准    : "败而不倒"——先保证每单风险<=2%，再说收益

开关机制（2026-11-02 启用提示 + 双级开关）：
  1. 全局开关: 环境变量 SP_DISCIPLINE_STRICT (默认1=严格)/ 0=宽松
  2. 查询开关: strict=true|false（默认 None=跟随全局）
     - strict=True  : L1 大市空头 → 一票否决（"回避"）——陈江挺"大市不好不买"
     - strict=False : L1 只提示不否决——仍输出个股参考计划，但明确标注"环境不允许"
  3. 启用提示: 每次响应带 framework 段（来源/范围/提示），L1 拦截时附专门 banner，
     提示本判定来自陈江挺执行纪律层，且不替代价值判断。

数据通道：SpDataService.query_raw (PG优先)。复用 market_regime / signal_engine。
"""
import os
from typing import Optional

from ..data_service import SpDataService
from .market_regime import get_market_regime, DEFAULT_INDEX
from .signal_engine import _load_daily, _detect_breakout, _resolve_date, _safe_float, calc_all_for_analysis


# 陈江挺纪律参数
MAX_SINGLE_RISK_PCT = 2.0      # 单笔亏损上限占总资金 %
STOP_PCT_DEFAULT = 8.0         # 默认止损幅度 %（超出则不应做）
TOTAL_RISK_CAP_PCT = 10.0      # 组合总风险敞口上限 %
DEFAULT_TOTAL_CAPITAL = 100_000.0  # 假设总资金（元），可覆盖
POSITION_SLOTS = 5             # 建议分散持仓数（3-5 → 取5，单一判断不致命）

# 全局开关：SP_DISCIPLINE_STRICT=1(默认,严格) / 0(宽松)
DISCIPLINE_STRICT_DEFAULT = os.environ.get("SP_DISCIPLINE_STRICT", "1") != "0"


def _finance_check(ts_code: str) -> dict:
    """基本面初筛（复用 diagnosis 财务数据，做'排除明显陷阱'的底线检查）。"""
    d = SpDataService.query_raw(
        "fina_indicator",
        "SELECT end_date, roe, yoy_profit FROM fina_indicator "
        "WHERE ts_code=? AND end_date=(SELECT MAX(end_date) FROM fina_indicator WHERE ts_code=?)",
        [ts_code, ts_code])
    if d.empty:
        return {"passed": False, "coverage": 0, "note": "无财务数据，未通过初筛（保守处理）"}
    r = d.iloc[0]
    roe = _safe_float(r.get("roe"))
    # 底线：ROE 不为负、财务数据存在即视为通过初筛（真正的价值评估留给基本面研究）
    roe_ok = roe is not None and roe >= 0
    return {
        "passed": roe_ok,
        "coverage": 1 if roe is not None else 0,
        "roe": roe,
        "end_date": str(r.get("end_date", "")).replace("-", ""),
        "note": f"ROE={roe:.1f}%" if roe is not None else "ROE缺失",
    }


def _technical_state(ts_code: str, date: Optional[str]) -> dict:
    """趋势状态 + 临界点突破检测（复用 signal_engine）。"""
    date = _resolve_date(date)
    d = _load_daily(ts_code, date, 200)
    if len(d) < 60:
        return {"coverage": 0, "trend": "数据不足", "note": "日线不足"}
    try:
        d = calc_all_for_analysis(d)
    except Exception:
        pass
    close = _safe_float(d["close"].iloc[-1])
    ma20 = _safe_float(d["MA20"].iloc[-1]) if "MA20" in d.columns and not d["MA20"].isna().iloc[-1] else None
    ma60 = _safe_float(d["MA60"].iloc[-1]) if "MA60" in d.columns and not d["MA60"].isna().iloc[-1] else None
    bo = _detect_breakout(d, close)

    # 趋势判断（陈江挺均线体系）
    if ma20 is None or ma60 is None:
        trend = "未知"
    else:
        if ma20 > ma60 and close > ma20:
            trend = "多头排列（上升趋势）"
        elif ma20 < ma60 and close < ma20:
            trend = "空头排列（下跌趋势）"
        else:
            trend = "纠缠（方向不明）"

    coverage = sum(1 for x in (ma20, ma60, close) if x is not None) / 3
    return {
        "coverage": coverage,
        "close": close,
        "ma20": ma20,
        "ma60": ma60,
        "trend": trend,
        "breakout": bo,       # 放量突破临界点信号或 None
        "trade_date": str(d["trade_date"].iloc[-1]).replace("-", ""),
    }


def _build_trading_plan(ts_code: str,
                        total_capital: float = DEFAULT_TOTAL_CAPITAL,
                        current_risk_pct: float = 0.0,
                        date: Optional[str] = None,
                        strict: Optional[bool] = None) -> dict:
    """五层交易纪律计划。返回结构化 dict（route 层包装 sp_success）。

    strict 开关（陈江挺框架开关）：
      None → 跟随全局 SP_DISCIPLINE_STRICT（默认严格=1）
      True → 严格：L1 大市空头即一票否决（"大市不好不买"）
      False→ 宽松：L1 只提示不否决，输出参考计划并标注环境不允许
    """
    # 生效的 strict 模式
    if strict is None:
        strict = DISCIPLINE_STRICT_DEFAULT

    # ---- L1 环境过滤 ----
    regime = get_market_regime(DEFAULT_INDEX, date)
    mkt_state = regime.get("mkt_state", "震荡")
    env_ok = mkt_state == "可操作(多头)"
    env = {
        "state": mkt_state,
        "close": regime.get("close"),
        "ma200": regime.get("ma200"),
        "ma60": regime.get("ma60"),
        "allowed": env_ok,         # 大市是否允许出手
        "note": regime.get("note", ""),
        "coverage": 1 if regime.get("confidence") == "高" else 0.5,
    }

    # ---- L2 标的/信号 ----
    fin = _finance_check(ts_code)
    tech = _technical_state(ts_code, date)
    # 允许入场 = 大市允许 且 基本面初筛通过 且 趋势偏多 且 接近/在临界点
    trend_ok = tech.get("trend", "").startswith("多头")
    at_breakout = tech.get("breakout") is not None
    target_ok = fin.get("passed") and (trend_ok or at_breakout)
    l2 = {
        "finance": fin,
        "technical": tech,
        "trend_ok": trend_ok,
        "at_breakout": at_breakout,
    }

    # ---- L3 风险预算（陈江挺核心：止损↔仓位↔风险预算闭环）----
    close = tech.get("close")
    ma20 = tech.get("ma20")
    # 止损价：优先取"跌破临界位/MA20"，否则用默认幅度
    stop_price = None
    stop_pct = None
    if close is not None:
        base = None
        if at_breakout and tech.get("breakout"):
            pass  # 突破后止损放突破位下方（用 MA20 近似）
        if ma20 is not None:
            base = ma20
        if base:
            stop_pct_tmp = (close - base) / close * 100
            if 0 < stop_pct_tmp <= STOP_PCT_DEFAULT:
                stop_pct = stop_pct_tmp
                stop_price = base
        if stop_pct is None:
            # 退化为默认幅度
            stop_pct = STOP_PCT_DEFAULT
            stop_price = close * (1 - stop_pct / 100)

    # 仓位反推：单笔风险 ≤ MAX_SINGLE_RISK_PCT% 总资金
    position_value = None
    capital_risk = total_capital * MAX_SINGLE_RISK_PCT / 100
    if stop_pct and stop_pct > 0 and close:
        position_value = capital_risk / (stop_pct / 100)
    # 单票仓位上限：永不满仓 + 分散3-5只 → 单票≤25%（1/4账户）
    max_single_position = total_capital * (1.0 / POSITION_SLOTS)  # 20%
    if position_value and position_value > max_single_position:
        position_value = max_single_position
    # 组合敞口校验：当前已用风险 + 本单风险 ≤ TOTAL_RISK_CAP_PCT%
    extra_risk_pct = MAX_SINGLE_RISK_PCT
    within_cap = (current_risk_pct + extra_risk_pct) <= TOTAL_RISK_CAP_PCT
    l3 = {
        "stop_price": round(stop_price, 2) if stop_price else None,
        "stop_pct": round(stop_pct, 2) if stop_pct else None,
        "single_risk_pct": MAX_SINGLE_RISK_PCT,
        "capital_risk_amt": round(capital_risk, 0),
        "suggested_position_value": round(position_value, 0) if position_value else None,
        "suggested_position_pct": round(position_value / total_capital * 100, 1) if position_value else None,
        "total_risk_cap_pct": TOTAL_RISK_CAP_PCT,
        "current_risk_pct": current_risk_pct,
        "within_cap": within_cap,
    }

    # ---- L4 退出管理 ----
    exit_breakeven = None
    if close is not None:
        exit_breakeven = close * 1.005  # 浮盈后上移保本（略高于成本）
    exit_plan = {
        "breakeven_stop": round(exit_breakeven, 2) if exit_breakeven else None,
        "trend_exit_line": round(ma20, 2) if ma20 else None,  # 跌破MA20离场
        "abnormal_volume_exit": "量价背离时离场（见 signal 引擎）",
    }

    # ---- 综合：是否值得参与 + 置信度 ----
    env_block = not env_ok
    fin_block = not fin.get("passed")
    risk_block = not within_cap
    # 环境拦截：严格模式下 L1 空头一票否决；宽松模式只提示不否决
    env_veto = env_block and strict
    env_warn = env_block and not strict
    # 环境/初筛/敞口任一硬性否决 → 不做
    if env_veto:
        verdict = "不参与（大市空头，安坐不动——陈江挺『大市不好不买』）"
        grade = "回避"
    elif fin_block:
        verdict = "不参与（基本面初筛未通过）"
        grade = "回避"
    elif not (trend_ok or at_breakout):
        verdict = "观望（趋势不明/未到临界点，等待突破确认）"
        grade = "观望"
    elif risk_block:
        verdict = "不参与（组合风险敞口已到上限）"
        grade = "回避"
    elif env_warn:
        # 宽松模式：大市环境不允许但给出参考计划（标注环境警告）
        verdict = "环境受限(参考)——大市空头，本计划仅供观察，不建议实际出手"
        grade = "环境受限"
    else:
        verdict = "可参与（环境+初筛+趋势/临界点均满足，风险可控）"
        grade = "可参与"

    coverage = (env["coverage"] + fin.get("coverage", 0) + tech.get("coverage", 0)) / 3
    confidence = "高" if coverage >= 0.8 else ("中" if coverage >= 0.5 else "低")

    # 框架启用提示 banner
    if strict:
        banner = "📐 陈江挺《炒股的智慧》执行纪律层已启用（严格模式）：L1 大市空头即一票否决——『大市不好不买』。本判定只回答『交易机会价值』，不做公司价值判断。"
    else:
        banner = "📐 陈江挺《炒股的智慧》执行纪律层已启用（宽松模式）：L1 大市仅提示不否决，输出参考计划。若需严格『大市不好不买』，请用 strict=true。"

    return {
        "ts_code": ts_code,
        "trade_date": tech.get("trade_date", regime.get("trade_date")),
        "grade": grade,
        "verdict": verdict,
        "confidence": f"{confidence}(覆盖度{coverage*100:.0f}%)",
        "capital": total_capital,
        # 陈江挺框架开关与启用提示
        "framework": {
            "name": "陈江挺《炒股的智慧》执行纪律层",
            "enabled": True,
            "strict": strict,
            "global_switch_env": "SP_DISCIPLINE_STRICT (1=严格/0=宽松)",
            "banner": banner,
        },
        "market_regime": env,
        "target": l2,
        "risk_budget": l3,
        "exit_plan": exit_plan,
        # 边界声明（不越界）
        "scope_note": "本引擎为执行纪律层，判定'交易机会价值'；不做公司内在价值判断（属基本面研究）。",
        "disclaimer": "胜率为概率表述；本计划默认当前仅作参考，风险自担。",
    }


def build_trading_plan(ts_code: str, total_capital: float = DEFAULT_TOTAL_CAPITAL,
                       current_risk_pct: float = 0.0,
                       date: Optional[str] = None,
                       strict: Optional[bool] = None) -> dict:
    """对外主入口 — 生成五层交易纪律计划（strict 见 _build_trading_plan）。"""
    return _build_trading_plan(ts_code, total_capital, current_risk_pct, date, strict)


if __name__ == "__main__":
    import json
    print(json.dumps(build_trading_plan("300750.SZ"), ensure_ascii=False, indent=2))
