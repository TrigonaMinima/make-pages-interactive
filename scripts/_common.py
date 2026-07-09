"""Shared constants and helpers between inject.py and mdwrap.py."""
from pathlib import Path

CSS_TAG = '<link rel="stylesheet" href="/lib/feedback.css">'
MDWRAP_MARKER = "<!-- cf-mdwrap generated -->"


def ensure_feedback_dir(root: Path) -> None:
    fb = root / "feedback"
    fb.mkdir(exist_ok=True)
    inbox = fb / "inbox.jsonl"
    if not inbox.exists():
        inbox.touch()
    history = fb / "history.json"
    if not history.exists():
        history.write_text("[]")


def find_files(root: Path, pattern: str, recursive: bool) -> list[Path]:
    if recursive:
        return sorted(p for p in root.rglob(pattern) if "feedback" not in p.parts)
    return sorted(root.glob(pattern))
