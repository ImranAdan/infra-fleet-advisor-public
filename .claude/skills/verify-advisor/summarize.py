#!/usr/bin/env python3
"""Print what a report proves: positions by result, coverage gaps, divergences.

Usage: summarize.py REPORT_JSON [BASE_REPORT_JSON]
With a base report, also prints every position whose result changed.
"""

import json
import sys
from collections import Counter


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def results(report: dict) -> dict[str, str]:
    return {
        f"{e['document_id']}/{e['proposition_id']}": e["status"]
        for e in report.get("intent_evaluations", [])
    }


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    report = load(sys.argv[1])
    head = results(report)
    counts = Counter(head.values())
    provenance = report.get("provenance", {})
    print(f"fleet commit:  {provenance.get('source_commit_sha', '?')}")
    print(f"intent digest: {provenance.get('intent_digest', '?')}")
    print(
        f"positions:     {len(head)} total, {len(head) - counts['declared_unverified']} decided, "
        f"{counts['satisfied']} satisfied, {counts['divergent']} divergent, "
        f"{counts['declared_unverified']} unproven"
    )
    gaps = [c for c in report.get("coverage", []) if c.get("status") != "ok"]
    print(f"coverage gaps: {len(gaps)}")
    for gap in gaps:
        print(f"  {gap['collector_id']}: {gap['status']} ({gap.get('error_summary')})")
    for key, status in sorted(head.items()):
        if status == "divergent":
            print(f"  divergent {key}")
    if len(sys.argv) == 3:
        base = results(load(sys.argv[2]))
        changed = sorted(k for k in base.keys() | head.keys() if base.get(k) != head.get(k))
        print(f"changed from base: {len(changed)}")
        for key in changed:
            print(f"  {key}: {base.get(key, 'absent')} -> {head.get(key, 'absent')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
