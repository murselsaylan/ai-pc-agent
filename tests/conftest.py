import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for candidate in [ROOT, ROOT / "backend", ROOT / "agent"]:
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)
