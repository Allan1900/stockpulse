"""
盘中实时告警引擎 — 交易时段运行

功能:
  - 价格突破告警 (涨幅/跌幅超阈值)
  - 成交量异动告警 (量比 > 阈值)
  - 板块异动告警 (行业整体涨跌幅)
  - 成交额 TOP 排行
  - 关注列表实时快照
"""
import os as _os
_DASH = _os.environ.get("SP_DASHBOARD_DIR") or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_ENGINE = _os.environ.get("SP_ENGINE_DIR") or _os.path.dirname(_os.path.abspath(__file__))
_DATA = _os.environ.get("SP_DATA_DIR") or _os.path.join(_os.path.expanduser("~"), "ashare_data")
import warnings; warnings.filterwarnings("ignore")
import pandas as pd
import numpy as np
import json
from datetime import datetime

CONFIG_PATH = _os.path.join(_DASH, "realtime_alert_config.json")

DEFAULT_CONFIG = {
    "price_up_threshold": 7.0, "price_down_threshold": -7.0,
    "volume_ratio_threshold": 5.0, "turnover_rank_top": 20,
    "sector_move_threshold": 3.0, "watchlist": [], "max_alerts": 20,
}

def load_config() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    except (FileNotFoundError, json.JSONDecodeError):
        return DEFAULT_CONFIG.copy()

def save_config(cfg: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

def _name_map() -> dict:
    from engine.query import sql as _sql
    df = _sql(None, "SELECT ts_code, name FROM stock_basic")
    return dict(zip(df["ts_code"], df["name"])) if df is not None and not df.empty else {}

def _industry_map() -> dict:
    from engine.query import sql as _sql
    df = _sql(None, "SELECT ts_code, industry FROM stock_basic")
    return dict(zip(df["ts_code"], df["industry"])) if df is not None and not df.empty else {}

def _snap() -> pd.DataFrame:
    from engine.realtime_cache import cached_snapshot
    return cached_snapshot(max_age=15)

def check_price_breakout(snap: pd.DataFrame, cfg: dict) -> list:
    """涨跌幅超阈值"""
    col_zdf = "zdf" if "zdf" in snap.columns else "pct_chg"
    col_code = "ts_code" if "ts_code" in snap.columns else "code"
    col_name = "name" if "name" in snap.columns else None
    if col_code is None or col_zdf not in snap.columns:
        return []
    df = snap.copy()
    df["_pct"] = pd.to_numeric(df[col_zdf], errors="coerce").dropna()
    nm = _name_map(); im = _industry_map()
    limit = max(1, cfg["max_alerts"] // 3)
    alerts = []
    for _, row in df.nlargest(limit, "_pct").iterrows():
        pct = row["_pct"]
        if np.isnan(pct) or pct < cfg["price_up_threshold"]: break
        code = row[col_code]
        alerts.append({"type": "price_up", "severity": "HIGH" if pct >= 9.5 else "MEDIUM",
            "ts_code": code, "name": row.get(col_name, nm.get(code, code)),
            "industry": im.get(code, ""), "value": round(pct, 2),
            "message": f" {row.get(col_name, nm.get(code, code))} 大涨 {pct:+.2f}%"})
    for _, row in df.nsmallest(limit, "_pct").iterrows():
        pct = row["_pct"]
        if np.isnan(pct) or pct > cfg["price_down_threshold"]: break
        code = row[col_code]
        alerts.append({"type": "price_down", "severity": "HIGH" if pct <= -9.5 else "MEDIUM",
            "ts_code": code, "name": row.get(col_name, nm.get(code, code)),
            "industry": im.get(code, ""), "value": round(pct, 2),
            "message": f" {row.get(col_name, nm.get(code, code))} 大跌 {pct:+.2f}%"})
    return alerts[:limit*2]

def check_volume_spike(snap: pd.DataFrame, cfg: dict) -> list:
    """量比超阈值"""
    col_vol = "volume" if "volume" in snap.columns else "vol"
    col_code = "ts_code" if "ts_code" in snap.columns else "code"
    if col_vol not in snap.columns or col_code not in snap.columns: return []
    from engine.query import sql as _sql
    top_codes = snap.nlargest(80, col_vol)[col_code].tolist()
    hist = _sql(None, """SELECT ts_code, AVG(vol) AS avg_vol FROM daily
        WHERE ts_code = ANY(%s)
        AND trade_date >= (SELECT MAX(trade_date) - 20 FROM daily) GROUP BY ts_code""",
        params=[top_codes])
    if hist is None or hist.empty: return []
    avg_map = dict(zip(hist["ts_code"], hist["avg_vol"]))
    snap_idx = snap.set_index(col_code)
    nm = _name_map(); alerts = []
    for code in top_codes[:25]:
        if code not in avg_map or avg_map[code] <= 0: continue
        cur = pd.to_numeric(snap_idx.loc[code, col_vol], errors="coerce")
        if np.isnan(cur) or cur <= 0: continue
        ratio = cur / avg_map[code]
        if ratio >= cfg["volume_ratio_threshold"]:
            alerts.append({"type": "volume_spike", "severity": "MEDIUM",
                "ts_code": code, "name": nm.get(code, code), "value": round(ratio, 1),
                "message": f" {nm.get(code, code)} 量比 {ratio:.1f}x"})
    return alerts[:15]

def check_turnover_top(snap: pd.DataFrame, cfg: dict) -> list:
    """成交额TOP"""
    col_t = "turnover" if "turnover" in snap.columns else "amount"
    col_code = "ts_code" if "ts_code" in snap.columns else "code"
    if col_t not in snap.columns: return []
    df = snap.copy(); df["_t_yi"] = pd.to_numeric(df[col_t], errors="coerce") / 1e8
    top = df.nlargest(cfg["turnover_rank_top"], "_t_yi")
    nm = _name_map()
    return [{"type": "turnover_top", "severity": "LOW", "ts_code": row[col_code],
        "name": nm.get(row[col_code], row.get("name", "")),
        "value": round(row["_t_yi"], 1),
        "message": f" {nm.get(row[col_code], row.get('name', ''))} 成交 {row['_t_yi']:.1f}亿"}
        for _, row in top.iterrows()]

def check_sector_movement(snap: pd.DataFrame, cfg: dict) -> list:
    """板块异动"""
    if "code" not in snap.columns or "zdf" not in snap.columns: return []
    from engine.realtime import is_trading_time
    if not is_trading_time(): return []
    im = _industry_map()
    df = snap.copy()
    clean = df["code"].str.replace("sh", "").str.replace("sz", "")
    df["_ts"] = clean + ".SH"
    df.loc[clean.str.len() == 6, "_ts"] = clean + ".SZ"
    df["_ind"] = df["_ts"].map(im)
    df = df[df["_ind"].notna() & (df["_ind"] != "")]
    df["_pct"] = pd.to_numeric(df["zdf"], errors="coerce")
    sec = df.groupby("_ind").agg(avg_pct=("_pct", "mean"), count=("_pct", "count")).reset_index()
    return [{"type": "sector_up", "severity": "LOW", "ts_code": "",
        "name": row["_ind"], "industry": row["_ind"],
        "value": round(row["avg_pct"], 2),
        "message": f" {row['_ind']} 板块 {row['avg_pct']:+.1f}% ({int(row['count'])}只)"}
        for _, row in sec.iterrows() if row["avg_pct"] >= cfg["sector_move_threshold"]][:10]

def check_watchlist(snap: pd.DataFrame, cfg: dict) -> list:
    """关注列表"""
    wl = cfg.get("watchlist", [])
    if not wl: return []
    col_code = "ts_code" if "ts_code" in snap.columns else "code"
    col_zdf = "zdf" if "zdf" in snap.columns else "pct_chg"
    nm = _name_map(); result = []
    for code in wl:
        match = snap[snap[col_code] == code]
        if match.empty: continue
        pct = pd.to_numeric(match.iloc[0][col_zdf], errors="coerce")
        pct_v = round(pct, 2) if not np.isnan(pct) else 0
        result.append({"type": "watchlist", "severity": "LOW",
            "ts_code": code, "name": nm.get(code, code), "value": pct_v,
            "message": f" {nm.get(code, code)}  {pct_v:+.2f}%"})
    return result

def run_intraday_alerts() -> dict:
    """运行盘中告警"""
    from engine.realtime import is_trading_time
    result = {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              "in_session": is_trading_time(), "alerts_count": 0, "alerts": []}
    if not result["in_session"]: return result
    cfg = load_config()
    snap = _snap()
    if snap is None or snap.empty or "error" in snap.columns: return result
    all_a = []
    all_a.extend(check_price_breakout(snap, cfg))
    all_a.extend(check_volume_spike(snap, cfg))
    all_a.extend(check_turnover_top(snap, cfg))
    all_a.extend(check_sector_movement(snap, cfg))
    all_a.extend(check_watchlist(snap, cfg))
    seen = set(); deduped = []
    sev_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    for a in all_a:
        key = a["type"] + a["ts_code"]
        if key not in seen: seen.add(key); deduped.append(a)
    deduped.sort(key=lambda x: (sev_order.get(x["severity"], 9), -abs(x.get("value", 0))))
    result["alerts"] = deduped[:cfg["max_alerts"]]
    result["alerts_count"] = len(result["alerts"])
    return result

def format_alerts_text(alerts: list, title: str = None) -> str:
    """格式化告警为推送文本"""
    if not alerts: return " 盘中告警 | 当前无告警"
    now = datetime.now().strftime("%m/%d %H:%M")
    t = title or f" 盘中实时告警 | {now}"
    lines = [t + "\n"]
    icons = {"price_up": " ", "price_down": " ", "volume_spike": " ",
             "turnover_top": " ", "sector_up": "  ", "watchlist": "  "}
    sev_i = {"HIGH": " ", "MEDIUM": " ", "LOW": ""}
    for a in alerts[:15]:
        icon = icons.get(a["type"], " ")
        sev = sev_i.get(a["severity"], "")
        lines.append(f"  {icon}{sev} {a['message']}")
    if len(alerts) > 15:
        lines.append(f"  ... 及另外 {len(alerts)-15} 条")
    return "\n".join(lines)