#!/usr/bin/env python3
"""Summarise `ncu --csv --page raw` exports of MFC runs: one row per kernel (mean over the launches of the last
profiled time step, i.e. the last third of the launches of each kernel when NCU_STEPS=3).

usage: ncu_summary.py RAW.csv [RAW2.csv ...] [--filter REGEX] [--md]
Columns: time (us, ncu replay with --clock-control none), registers/thread, theoretical / achieved occupancy (%),
DRAM GB read+write and % of peak DRAM throughput, local-memory load/store GB (l1tex local op bytes), FP64 pipe %,
L1 / L2 hit rate, warp instructions executed (millions).
"""

import csv
import re
import statistics
import sys

COLS = [
    ("time_us", "gpu__time_duration.sum", 1e-3),
    ("regs", "launch__registers_per_thread", 1),
    ("occ_theo%", "sm__maximum_warps_per_active_cycle_pct", 1),
    ("occ_ach%", "sm__warps_active.avg.pct_of_peak_sustained_active", 1),
    ("dram_GB", ("dram__bytes_read.sum", "dram__bytes_write.sum"), 1e-9),
    ("dram%", "gpu__dram_throughput.avg.pct_of_peak_sustained_elapsed", 1),
    ("lmem_ld_GB", "l1tex__t_bytes_pipe_lsu_mem_local_op_ld.sum", 1e-9),
    ("lmem_st_GB", "l1tex__t_bytes_pipe_lsu_mem_local_op_st.sum", 1e-9),
    ("fp64%", "sm__pipe_fp64_cycles_active.avg.pct_of_peak_sustained_active", 1),
    ("L1hit%", "l1tex__t_sector_hit_rate.pct", 1),
    ("L2hit%", "lts__t_sector_hit_rate.pct", 1),
    ("Minst", "smsp__inst_executed.sum", 1e-6),
]
UNIT = {"byte": 1, "Kbyte": 1e3, "Mbyte": 1e6, "Gbyte": 1e9, "ns": 1, "us": 1e3, "ms": 1e6, "nsecond": 1,
        "usecond": 1e3, "msecond": 1e6}


def short(name):
    name = re.sub(r"^m_[a-z_]+?_(s_[a-z_0-9]+?)_(\d+)_gpu", r"\1@\2", name)
    return name.replace("s_compute_advection_source_term_s_add_directional_advection_source_terms", "s_add_directional_adv_src")


def load(path):
    with open(path) as f:
        rows = list(csv.reader(f))
    head, units, data = rows[0], rows[1], rows[2:]
    idx = {h: i for i, h in enumerate(head)}
    per = {}
    for r in data:
        per.setdefault(r[idx["Kernel Name"]], []).append(r)

    def val(r, col):
        if col not in idx:
            return float("nan")
        s = r[idx[col]].replace(",", "")
        try:
            v = float(s)
        except ValueError:
            return float("nan")
        return v * UNIT.get(units[idx[col]], 1)

    out = {}
    for name, rs in per.items():
        rs.sort(key=lambda r: int(r[idx["ID"]]))
        last = rs[-max(1, len(rs) // 3):]
        rec = {}
        for label, col, scale in COLS:
            cols = col if isinstance(col, tuple) else (col,)
            rec[label] = statistics.mean(sum(val(r, c) for c in cols) for r in last) * scale
        out[name] = rec
    return out


def main():
    args = sys.argv[1:]
    md = "--md" in args
    if md:
        args.remove("--md")
    flt = None
    if "--filter" in args:
        i = args.index("--filter")
        flt = re.compile(args[i + 1])
        del args[i:i + 2]
    labels = [c[0] for c in COLS]
    for path in args:
        res = load(path)
        names = sorted((n for n in res if not flt or flt.search(n)), key=lambda n: -res[n]["time_us"])
        print(f"### {path}")
        if md:
            print("| kernel | " + " | ".join(labels) + " |")
            print("|---|" + "---:|" * len(labels))
            for n in names:
                print(f"| {short(n)} | " + " | ".join(f"{res[n][l]:.3g}" for l in labels) + " |")
        else:
            print(f"{'kernel':<52}" + "".join(f"{l:>11}" for l in labels))
            for n in names:
                print(f"{short(n):<52}" + "".join(f"{res[n][l]:11.3g}" for l in labels))
        print()


if __name__ == "__main__":
    main()
