#!/usr/bin/env python3
"""数据完整性校验"""

import sqlite3, os
from datetime import datetime

from ..config import get_config, db_path


# (db_key, table, composite_pk_columns)
DB_TABLES = [
    ("master", "stock_basic", ("ts_code",)),
    ("master", "trade_cal", ("exchange", "cal_date")),
    ("master", "index_basic", ("ts_code",)),
    ("master", "industry_classify", ("index_code", "industry_code")),
    ("master", "stock_delisted", ("ts_code",)),
    ("daily", "daily", ("ts_code", "trade_date")),
    ("daily", "daily_basic", ("ts_code", "trade_date")),
    ("financial", "fina_indicator", ("ts_code", "end_date")),
    ("financial", "income", ("ts_code", "end_date", "report_type")),
    ("financial", "balancesheet", ("ts_code", "end_date", "report_type")),
    ("financial", "cashflow", ("ts_code", "end_date", "report_type")),
    ("period", "weekly", ("ts_code", "week")),
    ("period", "monthly", ("ts_code", "month")),
    ("index", "index_daily", ("ts_code", "trade_date")),
    ("holders", "top10_holders", ("ts_code", "end_date", "holder_name")),
    ("holders", "stk_holdernumber", ("ts_code", "end_date")),
    ("lhb", "top_list", ("trade_date", "ts_code")),
]


def run_validate(deep=False):
    """执行完整性校验"""
    cfg = get_config()
    db_dir = cfg.db_dir
    print(f"数据完整性校验: {db_dir}")
    print()

    all_ok = True

    for db_key, table, pk_cols in DB_TABLES:
        path = db_path(db_key)
        if not os.path.exists(path):
            print(f"W  {db_key}.{table}: 数据库文件不存在")
            all_ok = False
            continue

        try:
            conn = sqlite3.connect(path)
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,)
            ).fetchone()
            if not exists:
                print(f"W  {db_key}.{table}: 表不存在")
                all_ok = False
                conn.close()
                continue

            cnt = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            cols = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            col_count = len(cols)

            issues = []

            if cnt == 0:
                issues.append("空表")

            # 主键去重
            pk_str = ", ".join(f'"{c}"' for c in pk_cols)
            total = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            distinct = conn.execute(
                f'SELECT COUNT(*) FROM (SELECT DISTINCT {pk_str} FROM "{table}")'
            ).fetchone()[0]
            if total != distinct:
                issues.append(f"主键重复: {total}行 vs {distinct}唯一")

            # 日期范围
            col_names = [c[1] for c in cols]
            date_col = None
            for candidate in ["trade_date", "end_date", "cal_date", "ann_date", "date"]:
                if candidate in col_names:
                    date_col = candidate
                    break

            if date_col and cnt > 0:
                min_d = conn.execute(
                    f'SELECT MIN("{date_col}") FROM "{table}"'
                ).fetchone()[0]
                max_d = conn.execute(
                    f'SELECT MAX("{date_col}") FROM "{table}"'
                ).fetchone()[0]
                date_info = f"日期: {min_d} ~ {max_d}" if min_d else ""
            else:
                date_info = ""

            status = "OK" if not issues else "W"
            if issues:
                all_ok = False
            issue_str = f" | {'; '.join(issues)}" if issues else ""
            print(f"{status} {db_key}.{table} ({col_count}列, {cnt:,}行) {date_info}{issue_str}")

            # 深度校验
            if deep and cnt > 0:
                for col_info in cols[:3]:
                    col_name = col_info[1]
                    nulls = conn.execute(
                        f'SELECT COUNT(*) FROM "{table}" WHERE "{col_name}" IS NULL'
                    ).fetchone()[0]
                    if nulls > cnt * 0.1:
                        print(f"     W {col_name}: {nulls:,} / {cnt:,} 为空值 ({nulls/cnt*100:.0f}%)")

            conn.close()

        except Exception as e:
            print(f"X  {db_key}.{table}: 校验失败 - {e}")
            all_ok = False

    print()
    if all_ok:
        print("OK 全部校验通过")
    else:
        print("W 部分校验存在问题")