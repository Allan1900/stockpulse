"""
数据导出 CLI 入口
"""
import os, sys
from datetime import datetime

from ..config import get_config, db_path


def run_export(ts_code, fmt, start, end, output):
    """导出数据"""
    from ..db.query import query_single_stock, get_stock_names, get_trade_dates

    cfg = get_config()
    if not start:
        start = cfg.default_start
    if not end:
        end = datetime.now().strftime("%Y%m%d")

    if ts_code:
        df = query_single_stock(ts_code, "*", start, end)
        if df.empty:
            print(f"无数据: {ts_code}")
            return

        name_map = get_stock_names()
        name = name_map.get(ts_code, ts_code)
        safe_name = name.replace("/", "-").replace("\\", "-")

        if not output:
            output = f"{ts_code}_{safe_name}_{start}_{end}.{fmt}"

        _write(df, output, fmt)
        print(f"已导出: {output} ({len(df)} 行)")
    else:
        from ..db.query import get_stock_list, query

        stocks = get_stock_list()
        total = 0

        for _, row in stocks.iterrows():
            code = row["ts_code"]
            name = row["name"]
            safe_name = name.replace("/", "-").replace("\\", "-")
            df = query_single_stock(code, "*", start, end)
            if df.empty:
                continue
            out_path = output or f"{code}_{safe_name}_{start}_{end}.{fmt}"
            _write(df, out_path, fmt)
            total += len(df)

        print(f"已导出: {len(stocks)} 只股票, {total:,} 行")


def _write(df, path, fmt):
    """写入文件"""
    if fmt == "csv":
        df.to_csv(path, index=False)
    elif fmt == "xlsx":
        df.to_excel(path, index=False)
    elif fmt == "parquet":
        df.to_parquet(path, index=False)