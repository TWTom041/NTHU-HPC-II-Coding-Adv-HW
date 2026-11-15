#!/usr/bin/env python3
"""Median / min / max / relative spread of grind times per variant from bench grind.csv files.

usage: summarize_grind.py grind.csv [more.csv ...] [--ref base]
Speedup is median(ref)/median(variant), ref = first variant seen unless --ref is given.
"""

import csv
import statistics
import sys


def main():
    args = sys.argv[1:]
    ref = None
    if "--ref" in args:
        i = args.index("--ref")
        ref = args[i + 1]
        del args[i:i + 2]
    data, order = {}, []
    for path in args:
        with open(path) as f:
            for row in csv.DictReader(f):
                v = row["variant"]
                try:
                    g = float(row["grind_ns"])
                except ValueError:
                    continue
                if g != g:
                    continue
                if v not in data:
                    data[v] = []
                    order.append(v)
                data[v].append(g)
    if not order:
        print("no data")
        return
    ref = ref or order[0]
    mref = statistics.median(data[ref])
    print(f"{'variant':<22} {'n':>3} {'median':>9} {'min':>9} {'max':>9} {'spread%':>8} {'speedup':>8}")
    for v in order:
        x = data[v]
        med = statistics.median(x)
        spread = (max(x) - min(x)) / med * 100
        print(f"{v:<22} {len(x):>3} {med:9.4f} {min(x):9.4f} {max(x):9.4f} {spread:8.2f} {mref / med:8.3f}")


if __name__ == "__main__":
    main()
