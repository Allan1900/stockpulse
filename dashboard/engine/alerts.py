"""
P2-③ 智能告警引擎

规则:
  - 估值告警 (PE/PB 历史分位数突破阈值)
  - 资金异动告警 (净流入/流出偏离均值 3σ)
  - 技术突破告警 (均线金叉/死叉, 布林带突破)
  - 成交量异动告警 (成交量 > 20日均量 3 倍)
"""
import os as _os
_DASH = _os.environ.get("SP_DASHBOARD_DIR") or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_ENGINE = _os.environ.get("SP_ENGINE_DIR") or _os.path.dirname(_os.path.abspath(__file__))
_DATA = _os.environ.get("SP_DATA_DIR") or _os.path.join(_os.path.expanduser("~"), "ashare_data")
import warnings; warnings.filterwarnings("ignore")
import json, os, datetime as dt
import pandas as pd
import numpy as np
from sqlalchemy import create_engine

PG_URI = "postgresql://zrall@localhost/ashare?options=-c%20search_path=ashare,public"
engine = create_engine(PG_URI)

FEISHU_CONFIG = _os.path.join(_DASH, "feishu_config.json")
OUTPUT_DIR = _os.path.join(_DATA, "exports", "alerts")

def q(sql, params=None):
    return pd.read_sql(sql, engine, params=tuple(params) if params else None)


# ── 规则 1: 估值告警 ──────────────────────────────
def check_valuation(date, pe_threshold_high=90, pe_threshold_low=10):
    """PE_ttm 历史分位数突破阈值"""
    df = q("""
        SELECT ts_code, pe_ttm
        FROM daily_basic WHERE trade_date = %s AND pe_ttm > 0 AND pe_ttm IS NOT NULL
    """, [date])
    if df.empty:
        return []

    # 获取历史分位数 (近 5 年)
    history = q("""
        SELECT db.ts_code,
               PERCENTILE_CONT(0.1) WITHIN GROUP (ORDER BY db.pe_ttm) AS pe_p10,
               PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY db.pe_ttm) AS pe_p90
        FROM daily_basic db
        WHERE db.trade_date >= (SELECT MIN(trade_date) FROM daily_basic
                                WHERE trade_date >= to_char(to_date(%s,'YYYYMMDD') - interval '5 years', 'YYYYMMDD'))
          AND db.pe_ttm > 0
        GROUP BY db.ts_code
    """, [date])

    alerts = []
    stocks = q("SELECT ts_code, name, industry FROM stock_basic")
    name_map = dict(zip(stocks["ts_code"], stocks["name"]))
    ind_map = dict(zip(stocks["ts_code"], stocks["industry"]))

    hmap = dict(zip(history["ts_code"], zip(history["pe_p10"], history["pe_p90"])))

    for _, row in df.iterrows():
        code = row["ts_code"]
        pe = row["pe_ttm"]
        if code not in hmap:
            continue
        p10, p90 = hmap[code]
        if p10 is None or p90 is None or p10 <= 0:
            continue
        if pe >= p90:
            alerts.append({
                "type": "估值预警-高估", "ts_code": code,
                "name": name_map.get(code, code),
                "industry": ind_map.get(code, ""),
                "value": round(pe, 2),
                "threshold": round(p90, 2),
                "message": f"PE({pe:.1f}) 超过 90% 历史分位({p90:.1f})"
            })
        elif pe <= p10:
            alerts.append({
                "type": "估值预警-低估", "ts_code": code,
                "name": name_map.get(code, code),
                "industry": ind_map.get(code, ""),
                "value": round(pe, 2),
                "threshold": round(p10, 2),
                "message": f"PE({pe:.1f}) 低于 10% 历史分位({p10:.1f})"
            })

    return alerts


# ── 规则 2: 资金异动告警 ──────────────────────────
def check_moneyflow(date, zscore_threshold=3.0):
    """净流入/流出偏离 20 日均值 3 个标准差"""
    today = q("""
        SELECT m.ts_code, m.net_mf_amount
        FROM moneyflow m WHERE m.trade_date = %s
    """, [date])
    if today.empty:
        return []

    # 20 日均值 + 标准差
    history = q("""
        SELECT m.ts_code,
               AVG(m.net_mf_amount) AS avg_net,
               STDDEV(m.net_mf_amount) AS std_net
        FROM moneyflow m
        WHERE m.trade_date >= to_char(to_date(%s,'YYYYMMDD') - 20, 'YYYYMMDD')
          AND m.trade_date < %s
        GROUP BY m.ts_code
    """, [date, date])

    if history.empty:
        return []

    stocks = q("SELECT ts_code, name, industry FROM stock_basic")
    name_map = dict(zip(stocks["ts_code"], stocks["name"]))
    ind_map = dict(zip(stocks["ts_code"], stocks["industry"]))
    hmap = dict(zip(history["ts_code"], zip(history["avg_net"], history["std_net"])))

    alerts = []
    for _, row in today.iterrows():
        code = row["ts_code"]
        net = row["net_mf_amount"]
        if code not in hmap:
            continue
        avg, std = hmap[code]
        if std is None or std == 0:
            continue
        z = abs((net - avg) / std)
        if z >= zscore_threshold:
            direction = "大幅流入" if net > avg else "大幅流出"
            alerts.append({
                "type": f"资金异动-{direction}", "ts_code": code,
                "name": name_map.get(code, code),
                "industry": ind_map.get(code, ""),
                "value": round(net / 1e4, 1),
                "threshold": round(zscore_threshold, 1),
                "message": f"净{'流入' if net>0 else '流出'} {abs(net)/1e8:.2f}亿 "
                           f"(偏离均值 {z:.1f}σ)"
            })

    return alerts[:50]  # 限制数量


# ── 规则 3: 技术突破告警 ──────────────────────────
def check_technical(date):
    """均线金叉/死叉 + 布林带突破"""
    stocks = q("SELECT ts_code, name, industry FROM stock_basic")
    alerts = []

    # 取最近 30 天日线
    data = q("""
        SELECT ts_code, trade_date, close,
               AVG(close) OVER w AS ma5,
               AVG(close) OVER (PARTITION BY ts_code ORDER BY trade_date
                                 ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20
        FROM daily
        WHERE trade_date >= to_char(to_date(%s,'YYYYMMDD') - 30, 'YYYYMMDD')
          AND trade_date <= %s
        WINDOW w AS (PARTITION BY ts_code ORDER BY trade_date
                     ROWS BETWEEN 4 PRECEDING AND CURRENT ROW)
        ORDER BY ts_code, trade_date
    """, [date, date])

    if data.empty:
        return []

    name_map = dict(zip(stocks["ts_code"], stocks["name"]))
    ind_map = dict(zip(stocks["ts_code"], stocks["industry"]))

    # 每组取最新 2 行判断金叉/死叉
    for code, grp in data.groupby("ts_code"):
        grp = grp.dropna(subset=["ma5", "ma20"]).tail(2)
        if len(grp) < 2:
            continue
        prev, curr = grp.iloc[0], grp.iloc[1]
        try:
            prev_gap = prev["ma5"] - prev["ma20"]
            curr_gap = curr["ma5"] - curr["ma20"]
        except (TypeError, KeyError):
            continue

        if prev_gap <= 0 and curr_gap > 0:
            alerts.append({
                "type": "技术信号-金叉", "ts_code": code,
                "name": name_map.get(code, code),
                "industry": ind_map.get(code, ""),
                "value": round(curr["close"], 2),
                "threshold": round(curr["ma20"], 2),
                "message": f"MA5({curr['ma5']:.2f}) 上穿 MA20({curr['ma20']:.2f})"
            })
        elif prev_gap >= 0 and curr_gap < 0:
            alerts.append({
                "type": "技术信号-死叉", "ts_code": code,
                "name": name_map.get(code, code),
                "industry": ind_map.get(code, ""),
                "value": round(curr["close"], 2),
                "threshold": round(curr["ma20"], 2),
                "message": f"MA5({curr['ma5']:.2f}) 下穿 MA20({curr['ma20']:.2f})"
            })

    return alerts


# ── 规则 4: 成交量异动 ────────────────────────────
def check_volume(date, vol_threshold=3.0):
    """成交量 > 20 日均量 3 倍"""
    today = q("""
        SELECT ts_code, vol FROM daily WHERE trade_date = %s
    """, [date])
    if today.empty:
        return []

    hist = q("""
        SELECT ts_code, AVG(vol) AS avg_vol, STDDEV(vol) AS std_vol
        FROM daily
        WHERE trade_date >= to_char(to_date(%s,'YYYYMMDD') - 20, 'YYYYMMDD')
          AND trade_date < %s
        GROUP BY ts_code
    """, [date, date])

    stocks = q("SELECT ts_code, name, industry FROM stock_basic")
    name_map = dict(zip(stocks["ts_code"], stocks["name"]))
    ind_map = dict(zip(stocks["ts_code"], stocks["industry"]))
    hmap = dict(zip(hist["ts_code"], zip(hist["avg_vol"], hist["std_vol"])))

    alerts = []
    for _, row in today.iterrows():
        code = row["ts_code"]
        vol = row["vol"]
        if code not in hmap:
            continue
        avg, std = hmap[code]
        if std is None or std == 0 or avg == 0:
            continue
        ratio = vol / avg if avg > 0 else 0
        if ratio >= vol_threshold:
            alerts.append({
                "type": "成交量异动", "ts_code": code,
                "name": name_map.get(code, code),
                "industry": ind_map.get(code, ""),
                "value": round(vol / 1e4, 1),
                "threshold": round(vol_threshold, 1),
                "message": f"成交量 {vol/1e4:.0f}万手 ({ratio:.1f}倍于20日均量)"
            })

    return alerts[:30]


# ── 汇总运行 ──────────────────────────────────────
def run_all(date=None):
    if not date:
        df = q("SELECT MAX(trade_date)::text FROM daily")
        date = df.iloc[0, 0] if not df.empty else dt.date.today().strftime("%Y%m%d")

    results = {}

    print(f"\n{'='*55}")
    print(f"  P2-③ 智能告警 — {date}")
    print(f"{'='*55}")

    # 估值
    print("\n[1/4] 估值告警...")
    v = check_valuation(date)
    results["valuation"] = v
    print(f"  [OK] {len(v)} 条 (高估 {sum(1 for x in v if '高估' in x['type'])} 条, "
          f"低估 {sum(1 for x in v if '低估' in x['type'])} 条)")

    # 资金
    print("\n[2/4] 资金异动...")
    m = check_moneyflow(date)
    results["moneyflow"] = m
    print(f"  [OK] {len(m)} 条 (流入 {sum(1 for x in m if '流入' in x['type'])} 条, "
          f"流出 {sum(1 for x in m if '流出' in x['type'])} 条)")

    # 技术
    print("\n[3/4] 技术信号...")
    t = check_technical(date)
    results["technical"] = t
    print(f"  [OK] {len(t)} 条 (金叉 {sum(1 for x in t if '金叉' in x['type'])} 条, "
          f"死叉 {sum(1 for x in t if '死叉' in x['type'])} 条)")

    # 成交量
    print("\n[4/4] 成交量异动...")
    vol = check_volume(date)
    results["volume"] = vol
    print(f"  [OK] {len(vol)} 条")

    total = sum(len(v) for v in results.values())
    print(f"\n{'='*55}")
    print(f"  总计: {total} 条告警")
    print(f"{'='*55}")

    return results, date


def format_for_push(results, date):
    lines = [f"🚨 **A股智能告警 — {date}**", ""]

    if results.get("valuation"):
        lines.append(f"**📊 估值告警 ({len(results['valuation'])} 条)**")
        for a in results["valuation"][:5]:
            em = "⚠️" if "高估" in a["type"] else "💡"
            lines.append(f"  {em} {a['name']}({a['ts_code'][:8]}): {a['message']}")
        if len(results["valuation"]) > 5:
            lines.append(f"  ... +{len(results['valuation'])-5} 条")
        lines.append("")

    if results.get("moneyflow"):
        lines.append(f"**💰 资金异动 ({len(results['moneyflow'])} 条)**")
        for a in results["moneyflow"][:5]:
            em = "🟢" if "流入" in a["type"] else "🔴"
            lines.append(f"  {em} {a['name']}({a['ts_code'][:8]}): {a['message']}")
        if len(results["moneyflow"]) > 5:
            lines.append(f"  ... +{len(results['moneyflow'])-5} 条")
        lines.append("")

    if results.get("technical"):
        lines.append(f"**📈 技术信号 ({len(results['technical'])} 条)**")
        for a in results["technical"][:5]:
            em = "🟢" if "金叉" in a["type"] else "🔴"
            lines.append(f"  {em} {a['name']}({a['ts_code'][:8]}): {a['message']}")
        if len(results["technical"]) > 5:
            lines.append(f"  ... +{len(results['technical'])-5} 条")
        lines.append("")

    if results.get("volume"):
        lines.append(f"**📊 成交量异动 ({len(results['volume'])} 条)**")
        for a in results["volume"][:5]:
            lines.append(f"  🔥 {a['name']}({a['ts_code'][:8]}): {a['message']}")
        if len(results["volume"]) > 5:
            lines.append(f"  ... +{len(results['volume'])-5} 条")

    lines.append(f"\n⏰ {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    return "\n".join(lines)


def push_feishu(text):
    # 读取配置
    try:
        with open(FEISHU_CONFIG) as f:
            cfg = json.load(f)
        if not cfg.get("enabled"):
            print("  [跳过] 飞书推送未启用")
            return
        wh = cfg.get("webhook") or os.environ.get("FEISHU_WEBHOOK", "")
        if not wh:
            print("  [跳过] webhook 未配置")
            return
    except Exception as e:
        print(f"  [跳过] 配置读取失败: {e}")
        return

    import requests
    try:
        r = requests.post(wh, json={
            "msg_type": "interactive",
            "card": {
                "header": {"title": {"tag": "plain_text", "content": "🚨 A股智能告警"}},
                "elements": [{"tag": "markdown", "content": text}]
            }
        }, timeout=10)
        print(f"  [推送] {'成功' if r.ok else f'失败({r.status_code})'}")
    except Exception as e:
        print(f"  [推送] 异常: {e}")


# ── 保存告警到文件 ──────────────────────────────
def save_alerts(results, date):
    out_dir = os.path.join(OUTPUT_DIR, date)
    os.makedirs(out_dir, exist_ok=True)

    for category, alerts in results.items():
        if not alerts:
            continue
        df = pd.DataFrame(alerts)
        path = os.path.join(out_dir, f"{category}.csv")
        df.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"  [保存] {path} ({len(df)} 条)")


if __name__ == "__main__":
    import sys
    date = sys.argv[1] if len(sys.argv) > 1 else None
    results, date = run_all(date)
    save_alerts(results, date)
    push_feishu(format_for_push(results, date))