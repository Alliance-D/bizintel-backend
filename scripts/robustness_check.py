"""Robustness / sensitivity check for the gap map (Kolb & Wagner 2025 style).

Re-scores the WHOLE grid with the production hurdle model under varied,
weakly-justified choices - the random seed, the training subsample (which
sectors), and the model family of both stages - then measures how stable three
things are versus the baseline map:

  1. the per-cell gap ranking      (Spearman correlation)
  2. the SET of "underserved" cells (overlap / Jaccard of the top band)
  3. the viability probability      (Spearman correlation of stage-1 output)

If these stay high across variants, the conclusion is robust, not an artefact of
arbitrary choices. Read-only on the database; writes a report to ml/artifacts/.
It does NOT touch the live predictions or the app.

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
from sklearn.ensemble import (
    ExtraTreesClassifier, ExtraTreesRegressor,
    HistGradientBoostingClassifier, HistGradientBoostingRegressor,
    RandomForestClassifier, RandomForestRegressor,
)
from sklearn.model_selection import GroupShuffleSplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train_and_score_opportunity_model import (  # noqa: E402
    ALL_FEATURES, SPLIT_GROUP_COLUMN, TARGET, HurdleModel, engine, load_features,
)

UNDERSERVED_PCTL = 80  # the "Underserved" band cut, matches gap_semantics


def _extra_trees(seed=42):
    return (ExtraTreesClassifier(n_estimators=300, min_samples_leaf=2, class_weight="balanced", random_state=seed, n_jobs=-1),
            ExtraTreesRegressor(n_estimators=300, min_samples_leaf=2, random_state=seed, n_jobs=-1))


def score_map(df: pd.DataFrame, clf, reg, train_idx=None) -> pd.DataFrame:
    """Fit the hurdle (on all rows, or a training subset) and return the gap
    percentile and viability for every cell x category - one full gap map."""
    X, y = df[ALL_FEATURES], df[TARGET].astype(float)
    h = HurdleModel(clf, reg).fit(
        X.iloc[train_idx] if train_idx is not None else X,
        y.iloc[train_idx] if train_idx is not None else y,
    )
    expected = np.clip(h.predict(X), 0, None)
    out = df[["grid_id", "business_category"]].copy()
    out["gap"] = expected - y.values
    out["pctl"] = out.groupby("business_category")["gap"].rank(pct=True) * 100
    out["viability"] = h.proba_present(X)
    out.index = out["grid_id"] + "|" + out["business_category"]
    return out


def compare(base: pd.DataFrame, var: pd.DataFrame) -> dict:
    """Stability of the gap ranking, the underserved set, and viability."""
    j = base.join(var[["pctl", "viability"]], rsuffix="_v", how="inner").dropna()
    gap_rho = float(spearmanr(j["pctl"], j["pctl_v"]).statistic)
    via_rho = float(spearmanr(j["viability"], j["viability_v"]).statistic)
    b = set(base.index[base["pctl"] >= UNDERSERVED_PCTL])
    v = set(var.index[var["pctl"] >= UNDERSERVED_PCTL])
    overlap = len(b & v) / len(b) if b else 1.0
    jac = len(b & v) / len(b | v) if (b | v) else 1.0
    return {"gap_spearman": round(gap_rho, 4), "underserved_overlap": round(overlap, 4),
            "underserved_jaccard": round(jac, 4), "viability_spearman": round(via_rho, 4)}


def main() -> None:
    """Run all variants against the baseline hurdle map and write the report."""
    df = load_features(engine())
    print(f"Baseline: hurdle on {len(df):,} rows ({df['grid_id'].nunique()} cells).")
    base = score_map(df, *_extra_trees(42))

    variants: list[tuple[str, str, pd.DataFrame]] = []
    # 1. random seed of both hurdle stages
    for s in [0, 1, 2, 7, 100]:
        variants.append((f"seed={s}", "seed", score_map(df, *_extra_trees(s))))
    # 2. model family of both stages
    families = {
        "random_forest": (RandomForestClassifier(n_estimators=250, min_samples_leaf=3, class_weight="balanced", random_state=42, n_jobs=-1),
                          RandomForestRegressor(n_estimators=250, min_samples_leaf=3, random_state=42, n_jobs=-1)),
        "hist_gradient_boosting": (HistGradientBoostingClassifier(random_state=42),
                                   HistGradientBoostingRegressor(random_state=42, max_iter=250, learning_rate=0.06)),
    }
    for name, (clf, reg) in families.items():
        variants.append((f"model={name}", "model", score_map(df, clf, reg)))
    # 3. training subsample (which 80% of sectors)
    gss = GroupShuffleSplit(n_splits=6, test_size=0.2, random_state=42)
    for i, (tr, _) in enumerate(gss.split(df, df[TARGET], df[SPLIT_GROUP_COLUMN])):
        variants.append((f"subsample={i}", "split", score_map(df, *_extra_trees(42), train_idx=tr)))

    rows = []
    print("\n  variant               gap-rho  underserved-overlap  viability-rho")
    for label, kind, v in variants:
        c = compare(base, v)
        c.update({"variant": label, "kind": kind})
        rows.append(c)
        print(f"  {label:20s}  {c['gap_spearman']:6.3f}    {c['underserved_overlap']:6.1%}          {c['viability_spearman']:6.3f}")

    res = pd.DataFrame(rows)
    by_kind = res.groupby("kind")[["gap_spearman", "underserved_overlap", "viability_spearman"]].mean().round(4)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "hurdle",
        "n_cells": int(df["grid_id"].nunique()),
        "n_rows": int(len(df)),
        "underserved_percentile_cut": UNDERSERVED_PCTL,
        "n_baseline_underserved": int((base["pctl"] >= UNDERSERVED_PCTL).sum()),
        "overall_mean_gap_spearman": round(float(res["gap_spearman"].mean()), 4),
        "overall_min_gap_spearman": round(float(res["gap_spearman"].min()), 4),
        "overall_mean_underserved_overlap": round(float(res["underserved_overlap"].mean()), 4),
        "overall_mean_viability_spearman": round(float(res["viability_spearman"].mean()), 4),
        "by_kind": by_kind.to_dict("index"),
        "variants": rows,
    }

    art = Path("ml/artifacts")
    art.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (art / f"robustness_report_{ts}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    md = [
        "# Gap-map robustness check (hurdle model)",
        "",
        f"Generated {summary['generated_at']}. Re-scored the grid "
        f"({summary['n_cells']} cells x categories = {summary['n_rows']} rows) with the hurdle model "
        f"under {len(variants)} variations (random seed, training subsample, model family), and "
        "compared each to the baseline map.",
        "",
        "## Headline",
        f"- Gap-ranking correlation across variants: **{summary['overall_mean_gap_spearman']:.3f}** "
        f"(worst {summary['overall_min_gap_spearman']:.3f})",
        f"- Underserved-set overlap: **{summary['overall_mean_underserved_overlap']:.1%}**",
        f"- Viability correlation: **{summary['overall_mean_viability_spearman']:.3f}**",
        f"- Baseline flags {summary['n_baseline_underserved']} underserved cells (percentile >= {UNDERSERVED_PCTL}).",
        "",
        "## By kind of choice",
        "| choice varied | gap Spearman | underserved overlap | viability Spearman |",
        "|---|---|---|---|",
    ]
    for kind, vals in by_kind.to_dict("index").items():
        md.append(f"| {kind} | {vals['gap_spearman']:.3f} | {vals['underserved_overlap']:.1%} | {vals['viability_spearman']:.3f} |")
    md += [
        "",
        "## How to read this",
        "- High correlations and overlap => the conclusion (which areas are underserved, and how "
        "viable each is) is robust to these arbitrary choices.",
        "- If the gap ranking is sensitive (especially to *model family*) but the underserved band and "
        "viability hold up, lean on the bands and the viability probability rather than exact ranks.",
        "",
        "Full per-variant numbers are in the companion JSON.",
    ]
    (art / f"robustness_report_{ts}.md").write_text("\n".join(md), encoding="utf-8")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        colors = {"seed": "#0E7A62", "model": "#B08033", "split": "#B9543A"}
        c = [colors[k] for k in res["kind"]]
        fig, ax = plt.subplots(1, 3, figsize=(13, 4))
        for a, col, title in zip(ax, ["gap_spearman", "underserved_overlap", "viability_spearman"],
                                 ["Gap ranking vs baseline", "Underserved overlap", "Viability vs baseline"]):
            a.bar(range(len(res)), res[col], color=c); a.set_ylim(0, 1); a.set_title(title); a.set_xticks([])
        fig.tight_layout(); fig.savefig(art / f"robustness_report_{ts}.png", dpi=120)
        print(f"\nWrote report: ml/artifacts/robustness_report_{ts}.(json|md|png)")
    except Exception as exc:
        print(f"\nWrote report: ml/artifacts/robustness_report_{ts}.(json|md)  [plot skipped: {exc}]")

    print(f"\nOverall: gap-rho {summary['overall_mean_gap_spearman']:.3f}, "
          f"underserved overlap {summary['overall_mean_underserved_overlap']:.1%}, "
          f"viability-rho {summary['overall_mean_viability_spearman']:.3f}")


if __name__ == "__main__":
    main()
