#!/usr/bin/env python3
"""Group an `nsys stats -r cuda_gpu_kern_sum -f csv` table by MFC kernel family, in ms per RK stage.

usage: nsys_groups.py A_cuda_gpu_kern_sum.csv [B_cuda_gpu_kern_sum.csv ...] [--labels a,b] [--md]
Stages are counted as the number of s_tvd_rk launches (one RK-update kernel per stage).
With several files, prints one column per file (ms/stage) so variants can be compared side by side.
"""

import csv
import sys

GROUPS = [
    ("WENO reconstruction (s_weno)", "s_weno_"),
    ("WENO input pack (s_pack_weno_input_arr)", "s_pack_weno_input_arr"),
    ("HLLC Riemann solver", "s_hllc_riemann_solver"),
    ("Riemann finalize copy", "s_finalize_riemann_solver"),
    ("Riemann state BC buffers", "s_populate_riemann_states"),
    ("Riemann init (zero flux_src)", "s_initialize_riemann_solver"),
    ("Advection source (s_add_directional_advection_source_terms)", "s_add_directional_advection_source_terms"),
    ("Flux difference (s_compute_advection_source_term)", "s_compute_advection_source_term"),
    ("RK update (s_tvd_rk)", "s_tvd_rk"),
    ("RHS copy q_cons -> q_cons_qp (s_compute_rhs)", "s_compute_rhs"),
    ("cons -> prim", "s_convert_conservative_to_primitive"),
    ("Halo / ghost-cell BC (m_boundary_common)", "m_boundary_common"),
    ("Characteristic BC (s_cbc)", "s_cbc"),
]


def load(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append((r["Name"], float(r["Total Time (ns)"]), int(r["Instances"])))
    stages = sum(n for name, _, n in rows if "s_tvd_rk" in name)
    groups = {g: 0.0 for g, _ in GROUPS}
    groups["other"] = 0.0
    for name, t, _ in rows:
        for g, pat in GROUPS:
            if pat in name:
                groups[g] += t
                break
        else:
            groups["other"] += t
    total = sum(groups.values())
    return {g: v / stages / 1e6 for g, v in groups.items()}, total / stages / 1e6, stages


def main():
    args = sys.argv[1:]
    md = "--md" in args
    if md:
        args.remove("--md")
    labels = None
    if "--labels" in args:
        i = args.index("--labels")
        labels = args[i + 1].split(",")
        del args[i:i + 2]
    data = [load(p) for p in args]
    labels = labels or [p.split("/")[-1].replace("_cuda_gpu_kern_sum.csv", "") for p in args]
    names = [g for g, _ in GROUPS] + ["other"]
    if md:
        print("| kernel group | " + " | ".join(f"{l} ms/stage" for l in labels) + " |")
        print("|---|" + "---:|" * len(labels))
        for g in names:
            print(f"| {g} | " + " | ".join(f"{d[0][g]:.3f}" for d in data) + " |")
        print("| **total** | " + " | ".join(f"**{d[1]:.3f}**" for d in data) + " |")
        print("| stages | " + " | ".join(str(d[2]) for d in data) + " |")
    else:
        print(f"{'group':<64}" + "".join(f"{l:>14}" for l in labels))
        for g in names:
            print(f"{g:<64}" + "".join(f"{d[0][g]:14.3f}" for d in data))
        print(f"{'TOTAL ms/stage':<64}" + "".join(f"{d[1]:14.3f}" for d in data))
        print(f"{'stages':<64}" + "".join(f"{d[2]:14d}" for d in data))


if __name__ == "__main__":
    main()
