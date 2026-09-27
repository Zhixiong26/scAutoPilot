#!/usr/bin/env python3
"""Review one completed Scanpy candidate and freeze the next optimization round."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from scautopilot.review import ReviewError, review_scanpy_run
except ImportError:  # generated projects vendor the package beside this script under tools/
    script_dir = Path(__file__).resolve().parent
    # Generated project: tools/scautopilot. Skill repository: scripts/ beside
    # scautopilot. Supporting both keeps the maintained entry point testable.
    sys.path.insert(0, str(script_dir))
    sys.path.insert(0, str(script_dir.parent))
    from scautopilot.review import ReviewError, review_scanpy_run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--session-id", required=True)
    args = parser.parse_args()
    result = review_scanpy_run(args.project, args.run_id, args.session_id)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReviewError, OSError, ValueError, KeyError) as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        raise SystemExit(2)
