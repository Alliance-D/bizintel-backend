"""Robustness / sensitivity check for the gap map (Kolb & Wagner 2025 style).

Re-scores the WHOLE grid under varied, weakly-justified modelling choices - the
random seed, the training subsample (which sectors), and the model family - then
measures how stable two things are:

  1. the per-cell gap ranking  (Spearman correlation vs the baseline map)
  2. the SET of cells flagged "underserved"  (overlap / Jaccard vs the baseline)

If both stay high across variants, the gap map is a robust conclusion, not an
artefact of arbitrary choices. This is read-only on the database and writes a
report to ml/artifacts/ - it does NOT touch the live predictions or the app.

Usage:
    python scripts/robustness_check.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.base import clone
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.model_selection import GroupShuffleSplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train_and_score_opportunity_model import (  # noqa: E402
    ALL_FEATURES, SPLIT_GROUP_COLUMN, TARGET,
    build_pipeline, candidate_models, engine, load_features,
)

UNDERSERVED_PCTL = 80  # the "Underserved" band cut, matches gap_semantics


def score_map(df: pd.DataFrame, model, train_idx=None) -> pd.DataFrame:
    """Fit a model (on all rows, or a training subset) and return the gap
    percentile for every cell x category - one full version of the gap map."""
    X, y = df[ALL_FEATURES], df[TARGET].astype(float)
    pipe = build_pipeline(clone(model))
    pipe.fit(X.iloc[train_idx] if train_idx is not None else X,
             y.iloc[train_idx] if train_idx is not None else y)
    expected = np.clip(pipe.predict(X), 0, None)
    out = df[["grid_id", "business_category"]].copy()
    out["gap"] = expected - y.values
    out["pctl"] = out.groupby("business_category")["gap"].rank(pct=True) * 100
    out.index = out["grid_id"] + "|" + out["business_category"]
    return out


def compare(base: pd.DataFrame, var: pd.DataFrame) -> tuple[float, float, float]:
    """Spearman of per-cell gap percentile, plus Jaccard and overlap of the
    underserved sets, between a variant map and the baseline map."""
    j = base[["pctl"]].join(var[["pctl"]], rsuffix="_v", how="inner").dropna()
    rho = float(spearmanr(j["pctl"], j["pctl_v"]).statistic)
    b = set(base.index[base["pctl"] >= UNDERSERVED_PCTL])
    v = set(var.index[var["pctl"] >= UNDERSERVED_PCTL])
    jac = len(b & v) / len(b | v) if (b | v) else 1.0
    overlap = len(b & v) / len(b) if b else 1.0
    return rho, jac, overlap


def main() -> None:
    """Run all variants against the baseline map and write the robustness report."""
    df = load_features(engine())
    models = candidate_models()
    base_model = models["extra_trees"]
    print(f"Baseline: extra_trees on {len(df):,} rows ({df['grid_id'].nunique()} cells).")
    base = score_map(df, base_model)

    variants: list[tuple[str, str, pd.DataFrame]] = []
    # 1. random seed (does the tree randomness reshuffle the map?)
    for s in [0, 1, 2, 7, 100]:
        m = ExtraTreesRegressor(n_estimators=300, min_samples_leaf=2, random_state=s, n_jobs=-1)
        variants.append((f"seed={s}", "seed", score_map(df, m)))
    # 2. model family (does the algorithm choice reshuffle the map?)
    for name in ["random_forest", "xgboost", "hist_gradient_boosting", "gradient_boosting"]:
        if name in models:
            variants.append((f"model={name}", "model", score_map(df, models[name])))
    # 3. training subsample (which 80% of sectors we train on)
    gss = GroupShuffleSplit(n_splits=6, test_size=0.2, random_state=42)
    for i, (tr, _) in enumerate(gss.split(df, df[TARGET], df[SPLIT_GROUP_COLUMN])):
        variants.append((f"subsample={i}", "split", score_map(df, base_model, train_idx=tr)))

    rows = []
    print("\n  variant               spearman  underserved-overlap  jaccard")
    for label, kind, v in variants:
        rho, jac, overlap = compare(base, v)
        rows.append({"variant": label, "kind": kind, "spearman": round(rho, 4),
                     "underserved_overlap": round(overlap, 4), "underserved_jaccard": round(jac, 4)})
        print(f"  {label:20s}  {rho:6.3f}    {overlap:6.1%}          {jac:.3f}")

    res = pd.DataFrame(rows)
    by_kind = res.groupby("kind")[["spearman", "underserved_overlap"]].mean().round(4)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_cells": int(df["grid_id"].nunique()),
        "n_rows": int(len(df)),
        "underserved_percentile_cut": UNDERSERVED_PCTL,
        "n_baseline_underserved": int((base["pctl"] >= UNDERSERVED_PCTL).sum()),
        "overall_mean_spearman": round(float(res["spearman"].mean()), 4),
        "overall_min_spearman": round(float(res["spearman"].min()), 4),
        "overall_mean_underserved_overlap": round(float(res["underserved_overlap"].mean()), 4),
        "overall_min_underserved_overlap": round(float(res["underserved_overlap"].min()), 4),
        "by_kind": by_kind.to_dict("index"),
        "variants": rows,
    }

    art = Path("ml/artifacts")
    art.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (art / f"robustness_report_{ts}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    md = [
        "# Gap-map robustness check",
        "",
        f"Generated {summary['generated_at']}. Re-scored the whole grid "
        f"({summary['n_cells']} cells x categories = {summary['n_rows']} rows) under "
        f"{len(variants)} variations of choices made without strong justification "
        "(random seed, training subsample, model family), and compared each to the "
        "baseline map.",
        "",
        "**Two questions:** does the per-cell gap *ranking* stay the same (Spearman), "
        "and do the same cells stay flagged *underserved* (overlap of the top band)?",
        "",
        "## Headline",
        f"- Mean rank correlation across variants: **{summary['overall_mean_spearman']:.3f}** "
        f"(worst {summary['overall_min_spearman']:.3f})",
        f"- Mean underserved-set overlap: **{summary['overall_mean_underserved_overlap']:.1%}** "
        f"(worst {summary['overall_min_underserved_overlap']:.1%})",
        f"- Baseline flags {summary['n_baseline_underserved']} underserved cells "
        f"(percentile >= {UNDERSERVED_PCTL}).",
        "",
        "## By kind of choice",
        "| choice varied | mean Spearman | mean underserved overlap |",
        "|---|---|---|",
    ]
    for kind, vals in by_kind.to_dict("index").items():
        md.append(f"| {kind} | {vals['spearman']:.3f} | {vals['underserved_overlap']:.1%} |")
    md += [
        "",
        "## How to read this",
        "- Correlations near 0.95-0.99 and high overlap => the gap map is a robust "
        "conclusion; the same areas surface as underserved regardless of these choices.",
        "- Low/variable numbers (especially the *split* rows) => the map is sensitive to "
        "which data it saw, and the finding is fragile - lean on the coarse bands rather "
        "than exact ranks, and say so.",
        "",
        "Full per-variant numbers are in the companion JSON.",
    ]
    (art / f"robustness_report_{ts}.md").write_text("\n".join(md), encoding="utf-8")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(1, 2, figsize=(10, 4))
        colors = {"seed": "#0E7A62", "model": "#B08033", "split": "#B9543A"}
        c = [colors[k] for k in res["kind"]]
        ax[0].bar(range(len(res)), res["spearman"], color=c); ax[0].set_ylim(0, 1)
        ax[0].set_title("Rank correlation vs baseline"); ax[0].set_xticks([])
        ax[1].bar(range(len(res)), res["underserved_overlap"], color=c); ax[1].set_ylim(0, 1)
        ax[1].set_title("Underserved-set overlap vs baseline"); ax[1].set_xticks([])
        fig.tight_layout(); fig.savefig(art / f"robustness_report_{ts}.png", dpi=120)
        print(f"\nWrote report: ml/artifacts/robustness_report_{ts}.(json|md|png)")
    except Exception as exc:
        print(f"\nWrote report: ml/artifacts/robustness_report_{ts}.(json|md)  [plot skipped: {exc}]")

    print(f"\nOverall: mean Spearman {summary['overall_mean_spearman']:.3f}, "
          f"mean underserved overlap {summary['overall_mean_underserved_overlap']:.1%}")


if __name__ == "__main__":
    main()
