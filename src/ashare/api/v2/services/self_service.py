"""客户自助服务 — 订阅状态 / 交付记录（2026-11-01 P2）

读取 ~/.hermes/email-users.yaml（用户分级：admin 全功能 / vip 年卡有有效期）
与 ~/.hermes/customer_records/<name>/（交付文件 + 交互时间线），
供 REST /self/* 与 MCP get_self_* 消费。只读，不修改客户数据。
"""
from pathlib import Path
from datetime import date, datetime

import yaml

HOME = Path.home()
USERS_YAML = HOME / ".hermes" / "email-users.yaml"
RECORDS_DIR = HOME / ".hermes" / "customer_records"

_CACHE = {"ts": 0.0, "users": None}


def load_users() -> list[dict]:
    """解析 email-users.yaml → [{email, name, tier, since, expires, features, active}]"""
    import time
    now = time.time()
    if _CACHE["users"] is not None and now - _CACHE["ts"] < 30:
        return _CACHE["users"]

    users = []
    if USERS_YAML.exists():
        try:
            raw = yaml.safe_load(USERS_YAML.read_text(encoding="utf-8")) or {}
            for u in raw.get("users", []):
                tier = str(u.get("tier", "basic")).lower()
                expires = u.get("expires")
                # YAML 1.1 会把 "2027-08-12" 自动解析为 date 对象 → 兼容两种形态
                if isinstance(expires, (date, datetime)):
                    expires = expires.isoformat()
                active = True
                if expires:
                    try:
                        active = date(int(expires[:4]), int(expires[5:7]), int(expires[8:10])) >= date.today()
                    except Exception:
                        active = False
                users.append({
                    "email": u.get("email", ""),
                    "name": u.get("name", ""),
                    "tier": tier,
                    "since": u.get("since"),
                    "expires": expires,
                    "features": u.get("features", "standard" if tier == "vip" else "all"),
                    "active": active,
                })
        except Exception as e:
            users = [{"email": "", "name": "", "tier": "basic",
                      "error": str(e), "active": False}]
    _CACHE.update(ts=now, users=users)
    return users


def get_status(email: str) -> dict:
    """按邮箱查用户状态；未注册返回 basic 空档"""
    email = (email or "").strip().lower()
    for u in load_users():
        if u.get("email", "").lower() == email:
            return u
    return {"email": email, "name": None, "tier": "basic",
            "since": None, "expires": None, "features": "none", "active": False,
            "notice": "未注册用户（基础公开数据可用，研报/组合等需开通年卡）"}


def _customer_dir(email: str, name: str = None) -> Path:
    """定位客户目录：优先 <name>（中文名），未命中则扫描各目录 record.md 按邮箱反查"""
    if name:
        d = RECORDS_DIR / name
        if d.is_dir():
            return d
    if RECORDS_DIR.is_dir():
        for sub in RECORDS_DIR.iterdir():
            if not sub.is_dir():
                continue
            rec = sub / "record.md"
            if rec.exists() and email in rec.read_text(encoding="utf-8", errors="replace"):
                return sub
    return Path()


def list_deliveries(email: str, limit: int = 20) -> dict:
    """客户交付记录：customer_records/<name>/ 根 + deliveries/ 下的 pdf/md 文件"""
    status = get_status(email)
    name = status.get("name")
    deliveries = []
    cust_dir = _customer_dir(email, name)
    if cust_dir.is_dir():
            files = []
            for sub in (cust_dir, cust_dir / "deliveries"):
                if sub.is_dir():
                    files.extend(sub.glob("*.pdf"))
                    files.extend(sub.glob("*.md"))
            for f in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
                deliveries.append({
                    "file": f.name,
                    "kind": f.suffix.lstrip("."),
                    "size_kb": round(f.stat().st_size / 1024, 1),
                    "modified": f.stat().st_mtime,
                })
    return {
        "email": email,
        "name": name,
        "tier": status.get("tier"),
        "deliveries": deliveries,
        "total": len(deliveries),
    }


def can_access(email: str, resource: str) -> bool:
    """资源访问权：admin 全开；vip 可看研报/交付；basic 仅公开行情"""
    tier = get_status(email).get("tier", "basic")
    if resource in ("reports", "deliveries", "portfolio"):
        return tier in ("admin", "vip")
    return True
