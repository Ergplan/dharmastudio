"""Write the font catalog and presets to frontend/src/mock/typography.json (the VITE_MOCK fixture). Run after editing
engine/typography.py; tests/test_typography.py checks the file is current."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import colour as C  # noqa: E402
from engine import typography as T  # noqa: E402

OUT = ROOT / "frontend" / "src" / "mock" / "typography.json"


def payload() -> dict:
    return {"fonts": T.catalog_json(), "presets": {"presets": T.presets_json(), "sizes": T.SIZES, "default": T.DEFAULT_SETTING, "colour_modes": list(T.COLOUR_MODES), "states": list(T.STATES),
            "state_colours": {st: {"box": C.STATE_BOX[st], "text": C.STATE_TEXT[st], "border": C.STATE_ACCENT[st]} for st in T.STATES}}}


if __name__ == "__main__":
    OUT.write_text(json.dumps(payload(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
