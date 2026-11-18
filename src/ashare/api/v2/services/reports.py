"""研报生态服务 — 研报目录检索（2026-11-01 P2）

扫描本地研报产出目录，提供目录/正文/PDF 检索：
- ~/market-daily/  每日收盘日报（daily_YYYYMMDD.md / .pdf）
- ~/market-weekly/ 每周市场周报（{W}/weekly-*.md / .pdf）

研报由 daily_report_generator.py（日报）与 market-weekly skill 管线（周报）产出，
本服务只做目录索引（不写入），供 REST /reports 与 MCP get_reports 消费。
"""
from pathlib import Path

HOME = Path.home()
DAILY_DIR = HOME / "market-daily"
WEEKLY_DIR = HOME / "market-weekly"


def _safe_date(name: str) -> str:
    return name.replace("daily_", "").replace("weekly_", "").replace(".md", "").replace(".pdf", "")


def list_reports() -> dict:
    """扫描研报目录 → {daily: [...], weekly: [...]} 各含 {kind, date, title, md_path, pdf_path, size}"""
    out = {"daily": [], "weekly": []}

    if DAILY_DIR.is_dir():
        for f in sorted(DAILY_DIR.glob("daily_*.md"), reverse=True):
            base = f.name[:-3]  # 去掉 .md
            pdf = f.with_suffix(".pdf")
            date = _safe_date(f.name)
            out["daily"].append({
                "kind": "daily",
                "date": date,
                "title": f"每日收盘日报 {date[:4]}-{date[4:6]}-{date[6:8]}",
                "md_path": str(f),
                "pdf_path": str(pdf) if pdf.exists() else None,
                "size_kb": round(f.stat().st_size / 1024, 1),
            })

    if WEEKLY_DIR.is_dir():
        for sub in sorted(WEEKLY_DIR.iterdir(), reverse=True):
            if not sub.is_dir():
                continue
            for f in sorted(sub.glob("*.md"), reverse=True):
                pdf = f.with_suffix(".pdf")
                date = _safe_date(f.name)
                out["weekly"].append({
                    "kind": "weekly",
                    "week": sub.name,
                    "date": date,
                    "title": f"市场周报 {sub.name}",
                    "md_path": str(f),
                    "pdf_path": str(pdf) if pdf.exists() else None,
                    "size_kb": round(f.stat().st_size / 1024, 1),
                })

    return out


def _find(kind: str, date_or_week: str) -> tuple:
    """定位研报文件 → (md_path, pdf_path) 或 None"""
    if kind == "daily":
        base = DAILY_DIR / f"daily_{date_or_week}"
        md = base.with_suffix(".md")
        pdf = base.with_suffix(".pdf")
        if md.exists():
            return md, (pdf if pdf.exists() else None)
        return None
    if kind == "weekly":
        md = WEEKLY_DIR / date_or_week / f"{date_or_week}.md"
        pdf = WEEKLY_DIR / date_or_week / f"{date_or_week}.pdf"
        if not md.exists():
            # 目录内任意 md
            d = WEEKLY_DIR / date_or_week
            if d.is_dir():
                cands = sorted(d.glob("*.md"))
                if cands:
                    md = cands[0]
                    p = md.with_suffix(".pdf")
                    pdf = p if p.exists() else None
        if md.exists():
            return md, pdf
    return None


def get_report(kind: str, date_or_week: str, limit_chars: int = 4000) -> dict:
    """取研报元数据 + 正文预览（limit_chars 截断，防大正文撑爆响应）"""
    found = _find(kind, date_or_week)
    if not found:
        return {}
    md_path, pdf_path = found
    text = md_path.read_text(encoding="utf-8", errors="replace")
    return {
        "kind": kind,
        "date": date_or_week,
        "md_path": str(md_path),
        "pdf_path": str(pdf_path) if pdf_path else None,
        "chars": len(text),
        "preview": text[:limit_chars],
    }
