"""
P3-③ 条件盯盘助手 — Sentinal Engine

对标: 券商条件单 / Wind 异动提醒
用户自定义条件: 价格突破 + 估值阈值 + 资金异动 + 成交量放大
"""

import os as _os
_DASH = _os.environ.get("SP_DASHBOARD_DIR") or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_ENGINE = _os.environ.get("SP_ENGINE_DIR") or _os.path.dirname(_os.path.abspath(__file__))
_DATA = _os.environ.get("SP_DATA_DIR") or _os.path.join(_os.path.expanduser("~"), "ashare_data")
import warnings; warnings.filterwarnings("ignore")
import json, os, datetime as dt
import pandas as pd
from sqlalchemy import create_engine

PG_URI = "postgresql://zrall@localhost/ashare?options=-c%20search_path=ashare,public"
engine = create_engine(PG_URI)
CONFIG_PATH = _os.path.join(_DASH, "sentinel_config.json")
OUTPUT_DIR = _os.path.join(_DATA, "exports", "sentinel")

def q(sql, params=None):
    return pd.read_sql(sql, engine, params=list(params) if params else None)

# ── 配置管理 ──────────────────────────────────

DEFAULT_CONFIG = {
    "conditions": [
        {
            "id": "cond_001",
            "name": "PE_ttm 低于10 (价值陷阱)",
            "enabled": False,
            "type": "valuation",
            "field": "pe_ttm",
            "operator": "lt",
            "value": 10,
            "stocks": [],
            "industries": [],
            "push_feishu": True,
        },
        {
            "id": "cond_002",
            "name": "单日涨幅 > 9.5% (接近涨停)",
            "enabled": False,
            "type": "price",
            "field": "pct_chg",
            "operator": "gt",
            "value": 9.5,
            "stocks": [],
            "industries": [],
            "push_feishu": False,
        },
        {
            "id": "cond_003",
            "name": "主力净流入 > 1亿",
            "enabled": False,
            "type": "moneyflow",
            "field": "net_mf_amount",
            "operator": "gt",
            "value": 100000000,
            "stocks": [],
            "industries": [],
            "push_feishu": False,
        },
        {
            "id": "cond_004",
            "name": "成交量 > 5日均量 3倍 (放量突破)",
            "enabled": False,
            "type": "volume",
            "field": "vol_ratio",
            "operator": "gt",
            "value": 3.0,
            "stocks": [],
            "industries": [],
            "push_feishu": False,
        },
        {
            "id": "cond_005",
            "name": "北向资金净买入TOP10",
            "enabled": False,
            "type": "hsgt",
            "field": "net_amount",
            "operator": "gt",
            "value": 0,
            "stocks": [],
            "industries": [],
            "push_feishu": False,
        },
    ],
    "refresh_interval": 60,
    "push_enabled": False,
    "webhook": "",
}


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def get_stock_map():
    stocks = q("SELECT ts_code, name, industry FROM stock_basic")
    return dict(zip(stocks["ts_code"], stocks["name"])), dict(zip(stocks["ts_code"], stocks["industry"]))


# ── 条件检查引擎 ──────────────────────────────

def check_condition(cond, date, stock_pool=None):
    """检查单条条件"""
    dtype = cond["type"]
    field = cond["field"]
    op = cond["operator"]
    val = cond["value"]
    enabled = cond.get("enabled", True)
    stocks_filter = cond.get("stocks", [])
    ind_filter = cond.get("industries", [])

    if not enabled:
        return []

    ops = {
        "gt": lambda a, b: a > b,
        "lt": lambda a, b: a < b,
        "gte": lambda a, b: a >= b,
        "lte": lambda a, b: a <= b,
        "eq": lambda a, b: abs(a - b) < 0.001,
    }
    op_func = ops.get(op)
    if not op_func:
        return []

    name_map, ind_map = get_stock_map()

    if dtype == "valuation":
        df = q("SELECT ts_code, pe_ttm, pb FROM daily_basic WHERE trade_date=%s", [date])
        if df.empty: return []
        results = []
        for _, r in df.iterrows():
            if stocks_filter and r["ts_code"] not in stocks_filter: continue
            if ind_filter and ind_map.get(r["ts_code"], "") not in ind_filter: continue
            if op_func(r.get(field, 0), val):
                results.append({
                    "ts_code": r["ts_code"],
                    "name": name_map.get(r["ts_code"], ""),
                    "industry": ind_map.get(r["ts_code"], ""),
                    "field": field,
                    "current": round(r.get(field, 0), 2),
                    "threshold": val,
                    "cond_name": cond["name"],
                    "message": f"{field}={r.get(field,0):.2f} 满足条件({op} {val})",
                })
        return results

    elif dtype == "price":
        df = q("SELECT ts_code, close, pct_chg, high, low FROM daily WHERE trade_date=%s", [date])
        if df.empty: return []
        results = []
        for _, r in df.iterrows():
            if stocks_filter and r["ts_code"] not in stocks_filter: continue
            if ind_filter and ind_map.get(r["ts_code"], "") not in ind_filter: continue
            curr_val = r.get(field, 0)
            if curr_val is None: continue
            if op_func(curr_val, val):
                results.append({
                    "ts_code": r["ts_code"],
                    "name": name_map.get(r["ts_code"], ""),
                    "industry": ind_map.get(r["ts_code"], ""),
                    "field": field,
                    "current": round(curr_val, 2),
                    "threshold": val,
                    "cond_name": cond["name"],
                    "message": f"{field}={curr_val:+.2f}% 触发条件",
                })
        return results

    elif dtype == "moneyflow":
        df = q("SELECT ts_code, net_mf_amount, buy_elg_amount FROM moneyflow WHERE trade_date=%s", [date])
        if df.empty: return []
        results = []
        for _, r in df.iterrows():
            if stocks_filter and r["ts_code"] not in stocks_filter: continue
            if ind_filter and ind_map.get(r["ts_code"], "") not in ind_filter: continue
            curr_val = r.get(field, 0) or 0
            if op_func(curr_val, val):
                results.append({
                    "ts_code": r["ts_code"],
                    "name": name_map.get(r["ts_code"], ""),
                    "industry": ind_map.get(r["ts_code"], ""),
                    "field": field,
                    "current": round(curr_val / 1e8, 2),
                    "threshold": round(val / 1e8, 2),
                    "cond_name": cond["name"],
                    "message": f"主力净流入 {curr_val/1e8:.2f}亿 (> {val/1e8:.2f}亿)",
                })
        return results

    elif dtype == "volume":
        today = q("SELECT ts_code, vol, amount FROM daily WHERE trade_date=%s", [date])
        if today.empty: return []
        hist = q("""
            SELECT ts_code, AVG(vol) AS avg_vol
            FROM daily
            WHERE trade_date>=to_char(to_date(%s,'YYYYMMDD')-10,'YYYYMMDD')
              AND trade_date<%s
            GROUP BY ts_code
        """, [date, date])
        vol_map = dict(zip(hist["ts_code"], hist["avg_vol"]))
        results = []
        for _, r in today.iterrows():
            if stocks_filter and r["ts_code"] not in stocks_filter: continue
            if ind_filter and ind_map.get(r["ts_code"], "") not in ind_filter: continue
            avg_v = vol_map.get(r["ts_code"])
            if avg_v is None or avg_v == 0: continue
            ratio = r["vol"] / avg_v
            if op_func(ratio, val):
                results.append({
                    "ts_code": r["ts_code"],
                    "name": name_map.get(r["ts_code"], ""),
                    "industry": ind_map.get(r["ts_code"], ""),
                    "field": "vol_ratio",
                    "current": round(ratio, 2),
                    "threshold": val,
                    "cond_name": cond["name"],
                    "message": f"成交量 {ratio:.1f}倍于10日均量 (>{val:.1f}倍)",
                })
        return results

    return []


def check_all(date):
    """检查所有启用的条件"""
    cfg = load_config()
    results = []
    for cond in cfg["conditions"]:
        if not cond.get("enabled", True):
            continue
        alerts = check_condition(cond, date)
        if alerts:
            results.append({"condition": cond["name"], "alerts": alerts[:10], "count": len(alerts)})
    return results


def build_message(results, date):
    """构建推送消息"""
    lines = [f"👀 盯盘提醒 — {date}", ""]
    total = sum(r["count"] for r in results)
    if total == 0:
        lines.append("今日无触发条件 ✓")
        return "\n".join(lines)

    lines.append(f"共 {total} 条触发:")
    lines.append("")
    for r in results:
        lines.append(f"**{r['condition']}** ({r['count']} 条)")
        for a in r["alerts"][:5]:
            lines.append(f"  {a['name']} ({a['ts_code'][:6]}): {a['message']}")
        if r["count"] > 5:
            lines.append(f"  ... +{r['count']-5} 条")
        lines.append("")

    lines.append(f"⏰ {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("🤖 P3-③ 盯盘助手")
    return "\n".join(lines)


def push_feishu(msg):
    cfg = load_config()
    if not cfg.get("push_enabled"):
        return
    wh = cfg.get("webhook") or os.environ.get("FEISHU_WEBHOOK", "")
    if not wh:
        return
    import requests
    try:
        r = requests.post(wh, json={
            "msg_type": "interactive",
            "card": {
                "header": {"title": {"tag": "plain_text", "content": "👀 盯盘提醒"}},
                "elements": [{"tag": "markdown", "content": msg}],
            },
        }, timeout=10)
        print(f"  [推送] {'OK' if r.ok else f'FAIL({r.status_code})'}")
    except Exception as e:
        print(f"  [推送] 异常: {e}")