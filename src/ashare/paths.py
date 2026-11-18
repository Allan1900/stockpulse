"""统一路径解析 — 全部可用环境变量覆盖，便于自托管部署。

环境变量：
  SP_DATA_DIR       数据目录（SQLite 库、导出的研报/告警文件）
  SP_DASHBOARD_DIR  Streamlit 面板目录（含 engine/）
  SP_ENGINE_DIR     分析引擎目录（默认 <dashboard>/engine）

默认值面向「克隆仓库即可跑」：数据目录 ~/ashare_data，面板目录为仓库内 dashboard/。
"""
import os
from pathlib import Path


def _repo_root() -> Path:
    # src/ashare/paths.py → src → 仓库根
    return Path(__file__).resolve().parents[2]


DATA_DIR = Path(os.environ.get("SP_DATA_DIR") or (Path.home() / "ashare_data")).expanduser()
DASHBOARD_DIR = Path(os.environ.get("SP_DASHBOARD_DIR") or (_repo_root() / "dashboard")).expanduser()
ENGINE_DIR = Path(os.environ.get("SP_ENGINE_DIR") or (DASHBOARD_DIR / "engine")).expanduser()

MACRO_DB = DATA_DIR / "ashare_macro.db"
GLOBAL_MACRO_DB = DATA_DIR / "ashare_global_macro.db"


def ensure_dirs() -> None:
    """首次运行时创建需要的目录（幂等）。"""
    for p in (DATA_DIR, DATA_DIR / "exports", DASHBOARD_DIR):
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
