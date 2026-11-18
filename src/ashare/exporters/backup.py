"""数据库备份工具"""
import os, shutil, zipfile
from datetime import datetime
from pathlib import Path

from ..config import get_config


DB_FILES = [
    "ashare_master.db",
    "ashare_daily.db",
    "ashare_financial.db",
    "ashare_period.db",
    "ashare_moneyflow.db",
    "ashare_holders.db",
    "ashare_lhb.db",
    "ashare_index.db",
    "ashare_macro.db",
]


def run_backup():
    """备份所有数据库文件"""
    cfg = get_config()
    db_dir = cfg.db_dir
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"ashare_backup_{timestamp}.zip"
    backup_path = db_dir / backup_name

    # Collect all db files + wal/shm
    files_to_backup = []
    total_size = 0
    for fname in DB_FILES:
        path = db_dir / fname
        if path.exists():
            files_to_backup.append(path)
            total_size += path.stat().st_size
            # Also include -wal and -shm if they exist
            for ext in [".db-wal", ".db-shm"]:
                extra = db_dir / (fname + ext)
                if extra.exists():
                    files_to_backup.append(extra)

    print(f"备份 {len(files_to_backup)} 个文件 ({total_size/1024/1024:.1f} MB)")
    print(f"输出: {backup_path}")

    # Create zip
    with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as zf:
        for path in files_to_backup:
            arcname = path.name
            print(f"  + {arcname} ({path.stat().st_size/1024/1024:.1f} MB)")
            zf.write(path, arcname)

    final_size = backup_path.stat().st_size
    print(f"\n备份完成! 压缩比: {final_size/total_size*100:.1f}%")
    print(f"备份文件: {backup_path} ({final_size/1024/1024:.1f} MB)")
    return str(backup_path)