"""数据库状态查看"""
import os
import sqlite3
from ..config import get_config, db_path


DB_DISPLAY = [
    ("master", "基础信息", "master"),
    ("daily", "日线行情", "daily"),
    ("financial", "财务数据", "financial"),
    ("period", "周线月线", "period"),
    ("moneyflow", "资金流向", "moneyflow"),
    ("holders", "股东数据", "holders"),
    ("lhb", "龙虎榜", "lhb"),
    ("index", "指数行情", "index"),
    ("macro", "宏观经济", "macro"),
]


def show_status():
    """打印数据库状态概览"""
    cfg = get_config()
    db_dir = cfg.db_dir

    print(f"ashare 数据库状态")
    print(f"数据目录: {db_dir}")
    if cfg.loaded_from():
        print(f"配置文件: {cfg.loaded_from()}")
    print()

    total_rows = 0
    total_size = 0
    header = f"{'类别':12s} {'表':6s} {'行数':>10s} {'列数':>4s} {'大小':>8s}  内容"
    print(header)
    print("-" * len(header))

    for key, label, _ in DB_DISPLAY:
        path = db_path(key)
        if not os.path.exists(path):
            print(f"{label:12s} ❌ 文件不存在")
            continue

        sz = os.path.getsize(path)
        total_size += sz
        try:
            conn = sqlite3.connect(path)
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='meta'"
            ).fetchall()

            if not tables:
                conn.close()
                print(f"{label:12s} {'--':6s} {'--':>10s} 空文件")
                continue

            for (t,) in tables:
                cnt = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                cols = conn.execute(f'PRAGMA table_info("{t}")').fetchall()
                col_count = len(cols)
                total_rows += cnt
                size_str = f"{sz/1024/1024:.1f}MB" if sz > 1024 * 1024 else f"{sz/1024:.1f}KB"
                print(f"{label:12s} {t:6s} {cnt:>10,} {col_count:>4d} {size_str:>8s}")

            conn.close()
        except Exception as e:
            print(f"{label:12s} ERROR: {e}")

    print()
    print(f"总计: {total_rows:,} 行, {total_size/1024/1024:.1f} MB")


def get_db_status() -> dict:
    """返回数据库状态字典（供 Dashboard 使用）"""
    size_info = []
    for key, label, _ in DB_DISPLAY:
        path = db_path(key)
        if not os.path.exists(path):
            size_info.append({
                "label": label, "db_key": key,
                "size_mb": 0, "status": "missing",
            })
            continue
        try:
            conn = sqlite3.connect(path)
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name!='meta'"
            ).fetchall()
            has_data = bool(tables)
            conn.close()
            sz_mb = os.path.getsize(path) / 1024 / 1024
            size_info.append({
                "label": label, "db_key": key,
                "size_mb": round(sz_mb, 1),
                "status": "ok" if has_data else "empty",
            })
        except Exception:
            size_info.append({
                "label": label, "db_key": key,
                "size_mb": 0, "status": "error",
            })
    return {"size_info": size_info}


def get_stock_count() -> int:
    """获取股票总数"""
    conn = sqlite3.connect(db_path("master"))
    try:
        cnt = conn.execute("SELECT COUNT(*) FROM stock_basic").fetchone()[0]
        return cnt
    finally:
        conn.close()


def get_trading_days_count(start=None, end=None) -> int:
    """获取交易日数"""
    conn = sqlite3.connect(db_path("master"))
    try:
        sql = "SELECT COUNT(*) FROM trade_cal WHERE is_open=1"
        params = []
        if start:
            sql += " AND cal_date>=?"
            params.append(start)
        if end:
            sql += " AND cal_date<=?"
            params.append(end)
        return conn.execute(sql, params).fetchone()[0]
    finally:
        conn.close()