"""Condense results/*.json into results/summary.json (+ a printed digest). python summary.py"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
R = HERE / "results"
PERIODS = ["dev", "val", "blind"]


def load(pattern):
    out = {}
    for f in sorted(glob.glob(str(R / pattern))):
        j = json.load(open(f))
        for per, v in j.get("results", j.get("grid", {})).items():
            out.setdefault(per, v)
        out["_sha"] = j.get("prereg_sha256")
    return out


def ci(z, scale=100):
    if not z or z.get("lo") is None:
        return None
    return dict(n=z["n"], mean=round(z["mean"] * scale, 2), lo=round(z["lo"] * scale, 2), hi=round(z["hi"] * scale, 2),
                clusters=z.get("clusters"))


def main():
    S = {"periods": {}}
    for tf in (1, 3, 5, 10, 15):
        prim = load(f"primary_tf{tf}*.json")
        for per in PERIODS:
            if per not in prim:
                continue
            p = prim[per]
            row = {}
            for label in ("primary_clean", "primary_all_sessions", "all_contracts_front_clean"):
                row[label] = {code: dict(n=d["n"], xJ=ci(d.get("excess_J")), xA=ci(d.get("excess_A")), raw=ci(d.get("raw")),
                                         perm_p=d.get("perm_J", {}).get("p"))
                              for code, d in p[label]["30"].items()}
            row["horizons_I_primary"] = {h: ci(p["primary_clean"][h].get("I", {}).get("excess_J")) for h in p["primary_clean"]}
            row["horizons_I_front"] = {h: ci(p["all_contracts_front_clean"][h].get("I", {}).get("excess_J"))
                                       for h in p["all_contracts_front_clean"]}
            row["tails"] = p["tails"]
            S["periods"].setdefault(per, {})[f"tf{tf}"] = row
    for name in ("null", "geometry", "decomp", "dte", "volume", "splits"):
        d = load(f"{name}_tf5_*.json")
        for per in PERIODS:
            if per in d:
                S["periods"].setdefault(per, {})[name] = d[per]
    g = load("grid_tf5_*.json")
    for per in PERIODS:
        if per not in g:
            continue
        rows = g[per]
        summ = {}
        for code in ("G", "I"):
            for scope in ("primary", "front"):
                v = np.array([r[f"xJ30_{scope}"] for r in rows if r["code"] == code and r[f"xJ30_{scope}"] is not None
                              and r[f"n_{scope}"] >= 10])
                n = [r[f"n_{scope}"] for r in rows if r["code"] == code]
                summ[f"{code}_{scope}"] = dict(cells=int(len(v)), share_pos=float((v > 0).mean()) if len(v) else None,
                                               median_pct=float(np.median(v) * 100) if len(v) else None,
                                               q10_pct=float(np.percentile(v, 10) * 100) if len(v) else None,
                                               q90_pct=float(np.percentile(v, 90) * 100) if len(v) else None,
                                               median_n=float(np.median(n)))
        # the L neighbourhood around the primary cell (c .75, k 2, m 2, strict)
        summ["L_neighbourhood_I"] = {r["L"]: dict(n_primary=r["n_primary"], xJ30_primary=r["xJ30_primary"],
                                                  n_front=r["n_front"], xJ30_front=r["xJ30_front"])
                                     for r in rows if r["code"] == "I" and r["c"] == 0.75 and r["k"] == 2.0 and r["m"] == 2 and r["strict"]}
        summ["k_neighbourhood_I"] = {r["k"]: dict(n_front=r["n_front"], xJ30_front=r["xJ30_front"])
                                     for r in rows if r["code"] == "I" and r["c"] == 0.75 and r["L"] == 12 and r["m"] == 2 and r["strict"]}
        S["periods"].setdefault(per, {})["grid"] = summ
    (R / "summary.json").write_text(json.dumps(S, indent=1, default=float))
    for per, v in S["periods"].items():
        print("=" * 20, per)
        for tf in ("tf1", "tf3", "tf5", "tf10", "tf15"):
            if tf in v:
                pc = v[tf]["primary_clean"]
                fr = v[tf]["all_contracts_front_clean"]
                print(tf, "I primary", pc.get("I"), "\n    I front", fr.get("I"), "\n    G front", fr.get("G"))
        if "grid" in v:
            print("grid", json.dumps({k: x for k, x in v["grid"].items() if "neigh" not in k}))


if __name__ == "__main__":
    main()
