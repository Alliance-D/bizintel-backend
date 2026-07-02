"""Build a simple release manifest showing key files and project readiness."""
from pathlib import Path
import json
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
KEY_DIRS = ["backend/app", "backend/sql", "frontend/app", "frontend/components", "scripts", "docs", "deployment"]


def main() -> None:
    files = []
    for d in KEY_DIRS:
        base = ROOT / d
        if base.exists():
            for path in base.rglob("*"):
                if path.is_file():
                    files.append(str(path.relative_to(ROOT)))
    manifest = {
        "project": "BizIntel Kigali",
        "phase": "10",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(files),
        "key_files": files[:500],
    }
    out = ROOT / "release_manifest.json"
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
