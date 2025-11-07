# generate_manifest.py
from pathlib import Path
import json

# 1) Change this if your images live elsewhere
CARDS_DIR = Path("assets/cards")

# 2) File types you want to include
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

def is_image(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in IMAGE_EXTS

def main():
    if not CARDS_DIR.exists():
        raise SystemExit(f"Folder not found: {CARDS_DIR.resolve()}")

    # Collect image filenames (just the names; not full paths)
    names = [p.name for p in CARDS_DIR.iterdir() if is_image(p)]

    if not names:
        raise SystemExit(f"No image files found in {CARDS_DIR.resolve()}")

    # Optional: sort (natural-ish)
    names.sort(key=lambda s: s.lower())

    out_path = CARDS_DIR.parent / "cards.json"  # assets/cards.json
    out_path.write_text(json.dumps(names, indent=2), encoding="utf-8")

    print(f"Wrote {len(names)} entries to {out_path}")

if __name__ == "__main__":
    main()
