"""Print every difference between two compare_behaviour.py outputs (timings are shown, not compared).

    python tests/diff_fingerprints.py old.json new.json
"""
import json, sys
a, b = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
def walk(x, y, path):
    if isinstance(x, dict) and isinstance(y, dict):
        for k in sorted(set(x) | set(y)):
            if k == "timing_ms": continue
            if k not in x or k not in y: print("MISSING", path + "/" + k); continue
            walk(x[k], y[k], path + "/" + k)
    elif x != y: print("DIFF", path, str(x)[:120], "->", str(y)[:120])
walk(a, b, "")
print("timing A", a.get("timing_ms")); print("timing B", b.get("timing_ms"))
