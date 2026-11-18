"""ESG 评分引擎 — 基于公开财务数据的简易 ESG 评级

E (环境 0-100): 行业环境风险分类 × 碳排放敏感度
S (社会 0-100): 员工规模代理 × 纳税贡献 × 行业安全
G (治理 0-100): 股权集中度 × 国有/民营 × 财务杠杆

综合: ESG = E×30% + S×30% + G×40%
"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd
import numpy as np
from engine.query import sql as _sql, sql_one as _sql1

# ── 行业环境风险分类 ──────────────────────────────────

HIGH_POLLUTION = [
    "钢铁", "煤炭", "石化", "化工", "造纸", "有色", "电力",
    "建材", "水泥", "玻璃", "电解铝", "基础化工",
]

CLEAN_INDUSTRIES = [
    "新能源", "光伏", "风电", "锂电池", "储能", "新能源汽车",
    "环保", "节能", "清洁能源", "碳中和", "绿色电力",
]

def _industry_env_score(industry: str) -> float:
    """行业环境评分 0-100"""
    if not industry:
        return 50
    if any(c in industry for c in CLEAN_INDUSTRIES):
        return 85
    if any(p in industry for p in HIGH_POLLUTION):
        return 25
    # 制造业中性
    if "制造" in industry:
        return 50
    # 服务业偏高
    if any(s in industry for s in ["金融", "信息", "科技", "软件", "服务"]):
        return 70
    return 55

# ── E 评分 ─────────────────────────────────────────

def score_e(ts_code: str) -> dict:
    """环境评分: 行业分类 + 研发强度(环保投入proxy)"""
    info = _sql1(None, "SELECT name, industry FROM stock_basic WHERE ts_code=%s", [ts_code])
    if not info:
        return {"score": 50, "details": {"industry": "未知", "env_category": "未知"}}

    industry = info["industry"] or ""
    name = info["name"]

    # 基础行业分
    base = _industry_env_score(industry)

    # 研发投入修正 (研发费用/营收比, 从 fina_indicator 的 revenue_ps 和资本公积 proxy)
    fin = _sql1(None, "SELECT revenue_ps, capital_rese_ps FROM fina_indicator "
               "WHERE ts_code=%s ORDER BY end_date DESC LIMIT 1", [ts_code])
    rd_boost = 0
    if fin:
        rev_ps = fin.get("revenue_ps") or 0
        cap_ps = fin.get("capital_rese_ps") or 0
        # 资本公积高 = 研发投入多的公司通常资本公积高
        if cap_ps > rev_ps * 2 and rev_ps > 0:
            rd_boost = 10
        elif cap_ps > rev_ps and rev_ps > 0:
            rd_boost = 5

    score = min(100, base + rd_boost)
    return {"score": round(score, 1), "details": {
        "industry": industry, "env_category": "清洁" if base >= 70 else "中性" if base >= 45 else "高污染",
        "base_score": base, "rd_boost": rd_boost,
    }}

# ── S 评分 ─────────────────────────────────────────

def score_s(ts_code: str) -> dict:
    """社会评分: 员工规模proxy + 纳税贡献 + 行业安全"""
    info = _sql1(None, "SELECT name, industry FROM stock_basic WHERE ts_code=%s", [ts_code])
    if not info:
        return {"score": 50, "details": {}}

    industry = info["industry"] or ""
    name = info["name"]

    # 员工规模 proxy: 营业成本越高 ≈ 员工越多
    fin = _sql1(None, "SELECT revenue, n_income, total_oper_cost FROM income "
               "WHERE ts_code=%s ORDER BY end_date DESC LIMIT 1", [ts_code])
    score = 55  # 基础分

    details = {}
    if fin:
        revenue = fin.get("revenue") or 0
        op_cost = fin.get("total_oper_cost") or fin.get("operate_cost") or 0
        net_income = fin.get("n_income") or 0

        # 员工代理: 营业成本大 = 大雇主
        if op_cost > 1e11:  # >1000亿
            score += 15
            details["employer_scale"] = "大型"
        elif op_cost > 1e10:
            score += 8
            details["employer_scale"] = "中型"
        else:
            details["employer_scale"] = "小型"

        # 纳税贡献 (所得税费用近似 = 利润总额 × 25%)
        tax_proxy = abs(net_income * 0.25) if net_income > 0 else 0
        if revenue > 0:
            tax_ratio = tax_proxy / revenue
            if tax_ratio > 0.05:
                score += 10
                details["tax_contribution"] = "高"
            elif tax_ratio > 0.02:
                score += 5
                details["tax_contribution"] = "中"
            else:
                details["tax_contribution"] = "低"

        # 盈利企业加分 (持续经营能力 = 社会责任)
        if net_income > 0:
            score += 5
            details["profitable"] = True
        else:
            details["profitable"] = False

    # 行业安全修正
    if any(s in industry for s in ["煤炭", "钢铁", "建筑", "化工", "采矿"]):
        score -= 10
        details["safety_risk"] = "高"
    elif any(s in industry for s in ["金融", "信息", "软件", "服务"]):
        score += 5
        details["safety_risk"] = "低"

    score = max(10, min(95, score))
    return {"score": round(score, 1), "details": details}

# ── G 评分 ─────────────────────────────────────────

def score_g(ts_code: str) -> dict:
    """治理评分: 股权集中度 + 国有/民营 + 财务杠杆"""
    info = _sql1(None, "SELECT name, industry FROM stock_basic WHERE ts_code=%s", [ts_code])
    if not info:
        return {"score": 50, "details": {}}

    score = 60  # 基础分
    details = {}

    # 股权集中度 (第一大股东比例)
    holder = _sql(None, "SELECT holder_name, hold_ratio FROM top10_holders "
                "WHERE ts_code=%s ORDER BY end_date DESC, hold_ratio DESC LIMIT 1", [ts_code])
    if holder is not None and not holder.empty:
        top1_ratio = float(holder.iloc[0]["hold_ratio"]) if pd.notna(holder.iloc[0]["hold_ratio"]) else 0
        details["top1_ratio"] = round(top1_ratio, 1)
        if top1_ratio > 60:
            score -= 15  # 一股独大
            details["ownership"] = "高度集中"
        elif top1_ratio > 40:
            score -= 5
            details["ownership"] = "相对集中"
        elif top1_ratio > 20:
            score += 5
            details["ownership"] = "适度分散"
        else:
            score += 10
            details["ownership"] = "高度分散"
    else:
        details["top1_ratio"] = "未知"

    # 国有/民营识别: 用股票代码前缀 + 行业判断 (简化)
    # 600xxx/601xxx 多数为国企
    code_num = ts_code[:6]
    if code_num.startswith(("600", "601", "688")) or ts_code.endswith(".SH"):
        score += 5  # 国企通常治理规范
        details["type"] = "国有/混合"
    else:
        details["type"] = "民营"

    # 财务杠杆 (资产负债率)
    bs = _sql1(None, "SELECT total_assets, total_liab FROM balancesheet "
              "WHERE ts_code=%s ORDER BY end_date DESC LIMIT 1", [ts_code])
    if bs:
        ta = bs.get("total_assets") or 0
        tl = bs.get("total_liab") or 0
        if ta > 0:
            lev = tl / ta
            details["leverage"] = round(lev, 3)
            if lev > 0.85:
                score -= 15  # 高杠杆风险
                details["lev_risk"] = "极高"
            elif lev > 0.70:
                score -= 8
                details["lev_risk"] = "偏高"
            elif lev > 0.50:
                score -= 3
                details["lev_risk"] = "中等"
            elif lev > 0.20:
                score += 5
                details["lev_risk"] = "稳健"
            else:
                score += 10
                details["lev_risk"] = "保守"

    score = max(10, min(95, score))
    return {"score": round(score, 1), "details": details}

# ── ESG 综合 ───────────────────────────────────────

def esg_score(ts_code: str) -> dict:
    """完整 ESG 评分"""
    e = score_e(ts_code)
    s = score_s(ts_code)
    g = score_g(ts_code)

    # 综合: E30% + S30% + G40%
    composite = e["score"] * 0.30 + s["score"] * 0.30 + g["score"] * 0.40

    # 等级
    if composite >= 80: grade = "AAA"
    elif composite >= 70: grade = "AA"
    elif composite >= 60: grade = "A"
    elif composite >= 50: grade = "BBB"
    elif composite >= 40: grade = "BB"
    elif composite >= 30: grade = "B"
    else: grade = "CCC"

    info = _sql1(None, "SELECT name, industry FROM stock_basic WHERE ts_code=%s", [ts_code])
    return {
        "ts_code": ts_code,
        "name": info["name"] if info else ts_code,
        "industry": info["industry"] if info else "",
        "esg_score": round(composite, 1),
        "esg_grade": grade,
        "e_score": e["score"], "e_details": e["details"],
        "s_score": s["score"], "s_details": s["details"],
        "g_score": g["score"], "g_details": g["details"],
    }

def esg_screen(min_score: float = 40, top_n: int = 50) -> pd.DataFrame:
    """全市场 ESG 筛选"""
    stocks = _sql(None, "SELECT ts_code, name, industry FROM stock_basic WHERE list_status='L' ORDER BY ts_code")
    if stocks is None or stocks.empty:
        return pd.DataFrame()

    results = []
    for _, row in stocks.head(200).iterrows():  # 限制 200 只
        try:
            esg = esg_score(row["ts_code"])
            if esg["esg_score"] >= min_score:
                results.append({
                    "ts_code": row["ts_code"], "name": row["name"],
                    "industry": row["industry"],
                    "esg_score": esg["esg_score"], "esg_grade": esg["esg_grade"],
                    "E": esg["e_score"], "S": esg["s_score"], "G": esg["g_score"],
                })
        except:
            continue
        if len(results) >= top_n:
            break

    df = pd.DataFrame(results)
    if not df.empty:
        df = df.sort_values("esg_score", ascending=False)
    return df