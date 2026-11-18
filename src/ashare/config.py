"""配置系统 - 支持 YAML 文件 + 环境变量覆盖

搜索顺序: ./config.yaml -> ~/.ashare/config.yaml -> /etc/ashare/config.yaml
环境变量: ASHARE_DB_DIR, TUSHARE_TOKEN, ASHARE_DEFAULT_START, ASHARE_DEFAULT_END
"""
import os
import yaml
from pathlib import Path
from typing import Optional

from .paths import DATA_DIR


CONFIG_SEARCH_PATHS = [
    Path("config.yaml"),
    Path.home() / ".ashare" / "config.yaml",
    Path("/etc/ashare/config.yaml"),
]

ENV_MAP = {
    "db_dir": "ASHARE_DB_DIR",
    "tushare_token": "TUSHARE_TOKEN",
    "default_start": "ASHARE_DEFAULT_START",
    "default_end": "ASHARE_DEFAULT_END",
}

DEFAULTS = {
    "db_dir": str(DATA_DIR),
    "api_delay": 0.3,
    "default_start": "20250101",
    "default_end": None,  # None → today
}


class Config:
    """应用配置"""

    def __init__(self):
        self._data = dict(DEFAULTS)
        self._loaded_path = None
        self._load_file()
        self._apply_env()

    def _load_file(self):
        for path in CONFIG_SEARCH_PATHS:
            if path.exists():
                with open(path) as f:
                    cfg = yaml.safe_load(f) or {}
                self._loaded_path = path
                # Apply file config
                if "db_dir" in cfg:
                    self._data["db_dir"] = cfg["db_dir"]
                if "dates" in cfg:
                    if "default_start" in cfg["dates"]:
                        self._data["default_start"] = cfg["dates"]["default_start"]
                if "api" in cfg:
                    if "tushare_token" in cfg["api"] and cfg["api"]["tushare_token"]:
                        self._data["tushare_token"] = cfg["api"]["tushare_token"]
                    if "api_delay" in cfg["api"]:
                        self._data["api_delay"] = cfg["api"]["api_delay"]
                break

    def _apply_env(self):
        for key, env_name in ENV_MAP.items():
            val = os.environ.get(env_name)
            if val:
                self._data[key] = val

    @property
    def db_dir(self) -> Path:
        # 支持 ~ 与环境变量，避免部署时写死绝对路径
        import os as _os
        return Path(_os.path.expandvars(_os.path.expanduser(str(self._data["db_dir"]))))

    @property
    def tushare_token(self) -> Optional[str]:
        return self._data.get("tushare_token")

    @property
    def api_delay(self) -> float:
        return float(self._data["api_delay"])

    @property
    def default_start(self) -> str:
        return self._data["default_start"]

    @property
    def default_end(self) -> Optional[str]:
        return self._data.get("default_end")

    def get(self, key, default=None):
        return self._data.get(key, default)

    def loaded_from(self) -> Optional[str]:
        return str(self._loaded_path) if self._loaded_path else None

    def to_dict(self) -> dict:
        return dict(self._data)


# 全局单例（只读，线程安全）
_config: Optional["Config"] = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config


def db_path(db_key: str) -> str:
    """返回数据库文件的绝对路径"""
    mapping = {
        "master": "ashare_master.db",
        "daily": "ashare_daily.db",
        "financial": "ashare_financial.db",
        "period": "ashare_period.db",
        "index": "ashare_index.db",
        "moneyflow": "ashare_moneyflow.db",
        "holders": "ashare_holders.db",
        "lhb": "ashare_lhb.db",
        "macro": "ashare_macro.db",
        "global_macro": "ashare_global_macro.db",
    }
    fname = mapping.get(db_key)
    if not fname:
        raise ValueError(f"Unknown db_key: {db_key}")
    return str(get_config().db_dir / fname)