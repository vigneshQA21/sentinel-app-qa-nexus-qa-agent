"""Day-by-day progress log (docs/PROGRESS_LOG.md): `./nx log "what changed"` adds a bullet under today's date."""
from __future__ import annotations

from datetime import date
from pathlib import Path

HEADER = "# Progress log (day by day)\n\n"


def append_log(path: Path, text: str, day: date | None = None) -> str:
    """Appends '- text' under the heading '## YYYY-MM-DD' (created at the end if today's heading is not there yet).
    Existing entries are never changed. Returns the heading used."""
    heading = f"## {(day or date.today()).isoformat()}"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = path.read_text(encoding="utf-8") if path.exists() else HEADER
    bullet = "- " + " ".join(text.split())
    lines = body.rstrip("\n").split("\n")
    idx = next((i for i, ln in enumerate(lines) if ln == heading or ln.startswith(heading + " ")), None)   # "## 2026-10-24  (day 5: ...)" counts
    if idx is not None:
        end = next((i for i in range(idx + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        while end > idx + 1 and not lines[end - 1].strip():      # keep the bullet next to the day's last line
            end -= 1
        lines.insert(end, bullet)
    else:
        lines += ["", heading, "", bullet]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return heading
