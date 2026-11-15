#!/usr/bin/env python3
"""Compare two MFC parallel-IO restart files (restart_data/lustre_<step>.dat).

The file is the conservative state q_cons written with MPI-IO in global layout:
sys_size contiguous blocks of (m+1)(n+1)(p+1) float64 values.

usage: compare.py REF.dat TEST.dat [--nvars 8] [--json out.json]
Prints per-variable max |a-b|, max |a-b|/max(|a|,tiny) and the number of differing values;
"bit-identical" when every byte matches.
"""

import argparse
import json
import sys

import numpy as np

NAMES_5EQ_2F_3D = ["alpha_rho1", "alpha_rho2", "rho_u", "rho_v", "rho_w", "E", "alpha1", "alpha2"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ref")
    ap.add_argument("test")
    ap.add_argument("--nvars", type=int, default=8)
    ap.add_argument("--json")
    a = ap.parse_args()

    x = np.fromfile(a.ref, dtype=np.float64)
    y = np.fromfile(a.test, dtype=np.float64)
    if x.size != y.size:
        print(f"SIZE MISMATCH {x.size} vs {y.size}")
        sys.exit(2)
    nvar = a.nvars
    x = x.reshape(nvar, -1)
    y = y.reshape(nvar, -1)
    names = NAMES_5EQ_2F_3D if nvar == 8 else [f"q{i + 1}" for i in range(nvar)]

    out = {"ref": a.ref, "test": a.test, "cells": int(x.shape[1]), "vars": []}
    bitident = bool(np.array_equal(x.view(np.uint64), y.view(np.uint64)))
    finite = bool(np.isfinite(y).all())
    print(f"cells per var: {x.shape[1]}  bit-identical: {bitident}  all-finite(test): {finite}")
    print(f"{'var':>11} {'max|ref|':>12} {'max abs diff':>13} {'max rel diff':>13} {'n_diff':>10}")
    worst_rel = 0.0
    for i in range(nvar):
        d = np.abs(x[i] - y[i])
        scale = np.maximum(np.abs(x[i]), np.finfo(np.float64).tiny)
        rel = d / scale
        # relative error is meaningless where the reference is ~0 (e.g. velocities at rest): use the
        # MFC test-suite rule "abs <= tol OR rel <= tol" and report the field-normalised error too
        nrm = float(d.max() / max(np.abs(x[i]).max(), np.finfo(np.float64).tiny))
        ndiff = int(np.count_nonzero(x[i] != y[i]))
        r = {"var": names[i], "max_abs_ref": float(np.abs(x[i]).max()), "max_abs_diff": float(d.max()),
             "max_rel_diff": float(rel.max()), "max_diff_over_field_max": nrm, "n_diff": ndiff}
        out["vars"].append(r)
        worst_rel = max(worst_rel, nrm)
        print(f"{names[i]:>11} {r['max_abs_ref']:12.4e} {r['max_abs_diff']:13.4e} {r['max_rel_diff']:13.4e} {ndiff:10d}")
    out["bit_identical"] = bitident
    out["all_finite"] = finite
    out["worst_diff_over_field_max"] = worst_rel
    print(f"worst max|diff|/max|field| = {worst_rel:.3e}")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
