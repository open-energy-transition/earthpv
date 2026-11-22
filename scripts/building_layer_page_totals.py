#!/usr/bin/env python
"""Print an evidence atlas page's `totals` block (the figures its headline uses)."""
import json
import sys


def totals(path: str) -> dict:
    s = open(path, encoding="utf-8").read()
    i = s.index('"totals":') + len('"totals":')
    obj, _ = json.JSONDecoder().raw_decode(s[i:])
    return obj


if __name__ == "__main__":
    keys = sys.argv[1].split(",") if len(sys.argv) > 2 and "," in sys.argv[1] else None
    paths = sys.argv[2:] if keys else sys.argv[1:]
    for p in paths:
        t = totals(p)
        flat = {k: v for k, v in t.items() if isinstance(v, (int, float)) or v is None}
        if keys:
            flat = {k: flat.get(k) for k in keys}
        print(p, json.dumps(flat))
