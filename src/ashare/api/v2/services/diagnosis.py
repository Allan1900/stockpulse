"""
StockPulse AI 深度诊股引擎 — 多源交叉验证 深度个股诊断报告

2026-11-02 新增。把"AI 诊股"从单点打分升级为 **多源交叉验证**：
财务 / 资金 / 技术 / 宏观 四维度独立评分，再叠加 Popper 证伪否决 与
Soros 反身阶段，输出带置信度的综合诊断。契合用户投资哲学：
多源交叉验证 + Popper 证伪 + Soros 反身 + 置信度等级。

评分模型（综合 0-100）：
    final = Σ(维度得分 × 维度权重) × (1 - 证伪修正) + 反身阶段加成

- 维度权重：财务 0.30 / 资金 0.25 / 技术 0.30 / 宏观 0.15（数据缺失时按覆盖度归一化）
- 证伪修正：falsify_buy 负分强烈 → 整体下调（Popper 证伪优先）
- 反身加成：Soros 阶段 1(启动)/2(加速）→ 加成；4/5/6(狂欢/逆转/崩溃）→ 减成
- 置信度 = 有数据的分维度覆盖度加权（高>=80% 中>=50% 低<50%）

数据通道：SpDataService.query_raw（PG 优先 / SQLite 宏观降级）。
"""
from typing import Optional

from ..data_service import SpDataService
from .philosophy import falsify_buy, falsify_sell, identify_stage

# 维度权重
_DIM_WEIGHTS = {
    "financial": 0.30,
    "moneyflow": 0.25,
    "technical": 0.30,
    "macro": 0.15,
}


def _safe_float(v):
    try:
        f = float(v)
        return f if f == f else None  # NaN check
    except (TypeError, ValueError):
        return None


def _resolve_date(date: Optional[str]) -> str:
    """交易日 YYYYMMDD（默认最新交易日），去横杠归一化。"""
    if date:
        return date.replace("-", "")
    d = SpDataService.query_raw(
        "daily", "SELECT DISTINCT trade_date FROM daily ORDER BY trade_date DESC LIMIT 1")
    if d.empty:
        return ""
    d0 = str(d.iloc[0]["trade_date"])
    return d0.replace("-", "") if "-" in d0 else d0


# ── D1 财务维度 ──────────────────────────────────────────
def _score_financial(ts_code: str):
    """财务维度评分（0-100）。指标：ROE / 净利同比 / 营收同比 / 经营现金流同比 / 毛利率。"""
    score, found, evidence = 0.0, 0, []
    d = SpDataService.query_raw(
        "fina_indicator",
        "SELECT end_date, roe, yoy_profit, yoy_revenue, yoy_ocf, gross_margin "
        "FROM fina_indicator WHERE ts_code=? "
        "AND end_date=(SELECT MAX(end_date) FROM fina_indicator WHERE ts_code=?)",
        [ts_code, ts_code])
    if d.empty:
        return 50.0, found, evidence, "无财务数据"
    r = d.iloc[0]
    roe = _safe_float(r.get("roe"))
    yoy_pft = _safe_float(r.get("yoy_profit"))
    yoy_rev = _safe_float(r.get("yoy_revenue"))
    yoy_ocf = _safe_float(r.get("yoy_ocf"))
    gm = _safe_float(r.get("gross_margin"))
    end = str(r.get("end_date", "")).replace("-", "")

    def _norm(v, lo, hi):
        """线性映射到 0-100，越界截断。"""
        return max(0.0, min(100.0, 50 + (v - lo) / (hi - lo) * 100))

    def _valid(v, lo, hi):
        """数据健全性检查：值必须在合理区间，否则视为脏数据跳过。"""
        return (v is not None and lo <= v <= hi)

    # ROE（15%=优秀 5%=及格；合理区间 -50~100%）
    if _valid(roe, -50, 100):
        found += 1
        s = _norm(roe, 3, 18)
        score += s
        evidence.append(f"ROE={roe:.1f}% → {_grade(s)}")
    # 净利同比（合理区间 -200~500%）
    if _valid(yoy_pft, -200, 500):
        found += 1
        s = _norm(yoy_pft, -30, 40)
        score += s
        evidence.append(f"净利同比={yoy_pft:.1f}% → {_grade(s)}")
    # 营收同比（合理区间 -200~500%）
    if _valid(yoy_rev, -200, 500):
        found += 1
        s = _norm(yoy_rev, -20, 30)
        score += s
        evidence.append(f"营收同比={yoy_rev:.1f}% → {_grade(s)}")
    # 经营现金流同比（合理区间 -500~500%）
    if _valid(yoy_ocf, -500, 500):
        found += 1
        s = 50 + max(-50, min(50, yoy_ocf / 2))
        score += s
        evidence.append(f"经营现金流同比={yoy_ocf:.1f}% → {_grade(s)}")
    # 毛利率（35%=强 15%=弱；合理区间 -50~100%，脏数据会显示为亿级异常值需跳过）
    if _valid(gm, -50, 100):
        found += 1
        s = _norm(gm, 10, 40)
        score += s
        evidence.append(f"毛利率={gm:.1f}% → {_grade(s)}")

    if found == 0:
        return 50.0, 0, evidence, "无财务数据"
    return round(float(score) / found, 1), found, evidence, f"最新期 {end}"


# ── D2 资金维度 ──────────────────────────────────────────
def _score_moneyflow(ts_code: str, date: str):
    """资金维度评分（0-100）。主力口径 = 大单(lg)+特大单(elg) 净流入。

    只看近 N 个交易日主力净流入累计，与历史均值对比 → 0-100。
    """
    score, found, evidence = 50.0, 0, []
    # 最近 20 个交易日主力净流入（净额，单位千元）
    d = SpDataService.query_raw(
        "moneyflow",
        "SELECT trade_date, net_mf_amount FROM moneyflow "
        "WHERE ts_code=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 20",
        [ts_code, date])
    if d.empty or len(d) < 5:
        return 50.0, found, evidence, "资金数据不足"
    d = d.sort_values("trade_date")
    nets = d["net_mf_amount"].apply(_safe_float).dropna()
    found += 1
    # 近3日 vs 近10日 vs 近20日的净流入强度
    tot = nets.iloc[-1]  # 最新一日
    tot3 = nets.tail(3).sum()
    tot10 = nets.tail(10).sum()
    tot20 = nets.sum()

    def _strength(v):
        # 单位千元 → 亿元。>10亿强流入、<-10亿强流出
        v_yi = v / 100000.0
        return max(0.0, min(100.0, 50 + v_yi * 3))

    score = _strength(tot20)  # 以20日累计为主
    if tot3 > 0 and tot10 > 0:
        score = score * 0.7 + _strength(tot3) * 0.3  # 近3日动量加权
        evidence.append(f"近3日主力净流入 {tot3/100000:.2f}亿")
    evidence.append(f"近10日主力净流入 {tot10/100000:.2f}亿")
    evidence.append(f"近20日主力净流入 {tot20/100000:.2f}亿")
    return round(float(score), 1), found, evidence, f"最新 {d['trade_date'].iloc[-1]}"


# ── D3 技术维度 ──────────────────────────────────────────
def _score_technical(ts_code: str, date: str):
    """技术维度评分（0-100）。均线多空 / MACD / 位置 / 量能。"""
    from ....utils.indicators import calc_ma, calc_macd, calc_rsi
    score, found, evidence = 50.0, 0, []
    d = SpDataService.query_raw(
        "daily",
        "SELECT trade_date, open, high, low, close, vol, amount FROM daily "
        "WHERE ts_code=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 120",
        [ts_code, date])
    if d.empty or len(d) < 30:
        return 50.0, found, evidence, "技术数据不足"
    d = d.sort_values("trade_date").reset_index(drop=True)
    try:
        d = calc_ma(d)
        d = calc_macd(d)
        d = calc_rsi(d, periods=(14,))
    except Exception:
        pass
    last = d.iloc[-1]
    close = last["close"]

    # 均线多空排列（MA5>MA10>MA20>MA60）
    if not d["MA20"].isna().iloc[-1]:
        found += 1
        ma5, ma10, ma20, ma60 = (
            last.get("MA5"), last.get("MA10"), last.get("MA20"), last.get("MA60"))
        _ma_ok = []
        if ma5 and ma10:
            _ma_ok.append(ma5 > ma10)
        if ma10 and ma20:
            _ma_ok.append(ma10 > ma20)
        if ma20 and ma60 and not d["MA60"].isna().iloc[-1]:
            _ma_ok.append(ma20 > ma60)
        if _ma_ok:
            ratio = sum(_ma_ok) / len(_ma_ok)
            score = score * 0.6 + ratio * 100 * 0.4
            evidence.append(f"均线多空排列 {'多头' if ratio>0.5 else '空头'} "
                            f"(MA5={ma5:.2f} MA10={ma10:.2f} MA20={ma20:.2f})")

    # MACD 金叉/死叉
    if "MACD_DIF" in d.columns and not d["MACD_DIF"].iloc[-2:].isna().any():
        found += 1
        dif, dea = last.get("MACD_DIF"), last.get("MACD_DEA")
        hist = last.get("MACD_HIST")
        if dif is not None and dea is not None:
            if hist and hist > 0:
                score = score * 0.7 + 75 * 0.3
                evidence.append(f"MACD 多头(DIF={dif:.3f}>DEA={dea:.3f})")
            else:
                score = score * 0.7 + 30 * 0.3
                evidence.append(f"MACD 空头(DIF={dif:.3f}<DEA={dea:.3f})")

    # RSI 位置
    if "RSI14" in d.columns and not d["RSI14"].isna().iloc[-1]:
        found += 1
        rsi = last.get("RSI14")
        if rsi is not None:
            if rsi > 70:
                score = score * 0.8 + 30 * 0.2  # 超买回撤风险
                evidence.append(f"RSI14={rsi:.0f} 超买")
            elif rsi < 30:
                score = score * 0.8 + 70 * 0.2  # 超卖反弹机会
                evidence.append(f"RSI14={rsi:.0f} 超卖")
            else:
                score = score * 0.8 + (rsi) * 0.2
                evidence.append(f"RSI14={rsi:.0f} 中性")

    # 20日位置（当前价相对20日高低区间）
    if len(d) >= 20:
        found += 1
        hi20, lo20 = d["high"].tail(20).max(), d["low"].tail(20).min()
        pos = (close - lo20) / (hi20 - lo20) * 100 if hi20 > lo20 else 50
        score = score * 0.7 + pos * 0.3
        evidence.append(f"20日区间位置 {pos:.0f}%")

    # 量能（近5日均量 vs 近60日均量）
    vol_col = d["vol"].astype(float)
    if len(vol_col) >= 20:
        found += 1
        v5 = vol_col.tail(5).mean()
        v60 = vol_col.tail(60).mean() if len(vol_col) >= 60 else vol_col.mean()
        if v60 > 0:
            vr = v5 / v60
            if vr > 1.5:
                score = score * 0.8 + 70 * 0.2  # 放量
                evidence.append(f"量能放大(5/60日均={vr:.1f})")
            elif vr < 0.7:
                score = score * 0.8 + 35 * 0.2  # 缩量
                evidence.append(f"量能萎缩(5/60日均={vr:.1f})")

    if found == 0:
        return 50.0, 0, evidence, "技术数据不足"
    return round(float(score), 1), found, evidence, float(close)


# ── D4 宏观维度 ──────────────────────────────────────────
def _score_macro():
    """宏观维度评分（0-100）。取最新宏观数据做景气定性。

    数据通道：macro_data（PG）或 cn_* 宏观表降级。若都缺失则权重归零处理。
    """
    evidence = []
    # 尝试取 PMI（制造业景气先行指标）
    try:
        d = SpDataService.query_raw(
            "cn_pmi",
            "SELECT * FROM cn_pmi ORDER BY month DESC LIMIT 1")
        if not d.empty:
            val = None
            for col in ("pmi", "value", "制造业"):
                if col in d.columns and d.iloc[0][col] is not None:
                    val = _safe_float(d.iloc[0][col])
                    if val is not None:
                        break
            if val is not None:
                s = 50 + (val - 50) * 6  # 50 荣枯线
                evidence.append(f"制造业PMI={val:.1f} → {'扩张' if val>50 else '收缩'}")
                return round(max(20, min(80, s)), 1), 1, evidence, "制造业PMI"
    except Exception:
        pass
    # 回退 macro_data（PG）
    try:
        d = SpDataService.query_raw(
            "macro_data",
            "SELECT macro_name, value, macro_date FROM macro_data "
            "ORDER BY macro_date DESC LIMIT 1")
        if not d.empty:
            val = _safe_float(d.iloc[0].get("value"))
            name = str(d.iloc[0].get("macro_name", ""))
            if val is not None:
                s = 50 + val * 0.5
                evidence.append(f"宏观指标[{name}]={val}")
                return round(max(20, min(80, s)), 1), 1, evidence, name
    except Exception:
        pass
    return 50.0, 0, evidence, "宏观数据缺失"


# ── 工具函数 ─────────────────────────────────────────────
def _grade(s):
    """分数 → 档次。"""
    if s >= 75:
        return "优"
    if s >= 60:
        return "良"
    if s >= 40:
        return "中"
    return "弱"


def _confidence(cover_ratio):
    """覆盖度(0-1) → 置信度等级。"""
    if cover_ratio >= 0.8:
        return "高(>=80%)"
    if cover_ratio >= 0.5:
        return "中(>=50%)"
    return "低(<50%)"


# ── 综合诊断 ─────────────────────────────────────────────
def deep_diagnosis(ts_code: str, date: Optional[str] = None):
    """AI 深度诊股 — 4 维度 + 哲学仲裁，带置信度。返回 dict。"""
    date = _resolve_date(date)

    # 四维度独立评分
    fin_score, fin_n, fin_ev, fin_src = _score_financial(ts_code)
    mf_score, mf_n, mf_ev, mf_src = _score_moneyflow(ts_code, date)
    te_score, te_n, te_ev, te_src = _score_technical(ts_code, date)
    ma_score, ma_n, ma_ev, ma_src = _score_macro()

    # 覆盖度与置信度
    dims = {
        "financial": {"score": fin_score, "n": fin_n, "label": "财务",
                      "evidence": fin_ev, "source": fin_src},
        "moneyflow": {"score": mf_score, "n": mf_n, "label": "资金",
                      "evidence": mf_ev, "source": mf_src},
        "technical": {"score": te_score, "n": te_n, "label": "技术",
                      "evidence": te_ev, "source": te_src},
        "macro": {"score": ma_score, "n": ma_n, "label": "宏观",
                  "evidence": ma_ev, "source": ma_src},
    }
    # 有数据的维度权重归一化
    active = {k for k, v in dims.items() if v["n"] > 0}
    if not active:
        active = {"financial"}
    w_sum = sum(_DIM_WEIGHTS[k] for k in active)
    weights = {k: _DIM_WEIGHTS[k] / w_sum for k in active}

    # 加权综合
    final = sum(dims[k]["score"] * weights[k] for k in active)

    # 覆盖度置信度
    cover_ratio = len(active) / 4

    # ── 哲学仲裁 ──────────────────────────────────────────
    philosophy = {"buy_falsified": False, "sell_rebutted": False, "stage": None}
    try:
        buy_s, buy_r = falsify_buy(ts_code, date)
        sell_s, sell_r = falsify_sell(ts_code, date)
        philosophy["buy_falsified"] = buy_s < -0.30
        philosophy["sell_rebutted"] = sell_s > 0.30
        philosophy["buy_score"] = round(buy_s, 2)
        philosophy["sell_score"] = round(sell_s, 2)
        philosophy["buy_rules"] = buy_r
        philosophy["sell_rules"] = sell_r
        # Popper 证伪修正：买入被证伪 → 综合分下调
        if buy_s < -0.30:
            final -= 8
        elif buy_s < 0:
            final -= 3
        if sell_s > 0.30:
            final += 5  # 卖出被反驳 → 偏向持有
    except Exception:
        pass

    try:
        stage = identify_stage(ts_code, date)
        philosophy["stage"] = stage
        # Soros 反身阶段加成/减成
        stage_id = stage.get("stage", 0)
        if stage_id in (1, 2):  # 启动/加速
            final += 5
        elif stage_id in (4, 5, 6):  # 狂欢/逆转/崩溃
            final -= 10
    except Exception:
        pass

    final = round(max(0, min(100, final)), 1)

    # ── 观点判定（Popper 优先：被证伪则不追高） ──────────
    if philosophy.get("stage", {}).get("signal") in ("SELL", "回避", "减仓"):
        stance = "减持/回避"
    elif final >= 70 and not philosophy["buy_falsified"]:
        stance = "强势买入"
    elif final >= 55 and not philosophy["buy_falsified"]:
        stance = "增持"
    elif 45 <= final < 55:
        stance = "中性持有"
    elif 30 <= final < 45:
        stance = "减持观望"
    else:
        stance = "回避/回避"

    return {
        "ts_code": ts_code,
        "trade_date": date,
        "name": SpDataService.get_stock_name(ts_code),
        "final_score": final,  # 0-100
        "stance": stance,
        "confidence": _confidence(cover_ratio),
        "cover_ratio": round(cover_ratio, 2),
        "dimensions": {
            k: {
                "label": dims[k]["label"],
                "score": dims[k]["score"],
                "weight": round(weights.get(k, 0), 3),
                "grade": _grade(dims[k]["score"]),
                "source": dims[k]["source"],
                "evidence": dims[k]["evidence"],
            } for k in dims
        },
        "philosophy": {
            "buy_falsified": philosophy["buy_falsified"],
            "sell_rebutted": philosophy["sell_rebutted"],
            "buy_score": philosophy.get("buy_score"),
            "sell_score": philosophy.get("sell_score"),
            "stage": philosophy.get("stage"),
        },
    }


def quick_score(ts_code: str, date: Optional[str] = None):
    """简版评分 — 供 MCP 快速调用（精简输出）。"""
    d = deep_diagnosis(ts_code, date)
    return {
        "ts_code": d["ts_code"],
        "name": d["name"],
        "score": d["final_score"],
        "stance": d["stance"],
        "confidence": d["confidence"],
        "stage": (d["philosophy"].get("stage") or {}).get("name"),
        "buy_falsified": d["philosophy"]["buy_falsified"],
        "trade_date": d["trade_date"],
        "dimension_scores": {
            k: v["score"] for k, v in d["dimensions"].items()
        },
    }
