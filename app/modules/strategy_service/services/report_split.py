"""
report_split — the write-side of the split-artifact report delivery path.

Takes the same report dict each task already builds today (no compute
changes) and uploads it as several small named sections instead of one big
blob, so a tab that's never opened never gets downloaded or decoded. Section
boundaries mirror the report pages' own tabs — see each *_SECTIONS map below
for exactly which fields go where.

Field ownership for BACKTEST_SECTIONS was taken directly from the frontend
components that render each tab (report-sections.tsx, MetricsGrid.tsx,
CorrelationHeatmap, ConcentrationPanel, etc.) — every one of those components
already null-guards its own slice of `metrics` (e.g. `if (!risk) return
null`), so a field ending up in the "wrong" section degrades gracefully
(that panel just doesn't render) rather than crashing anything.

Only BACKTEST is populated for the first rollout pass (see the report
delivery plan's rollout order) — Optimization/Walkforward/Monte Carlo get
their own entries once the pattern is verified end-to-end on Backtest.
"""
from typing import Any

from app.utils.artifact_paths import ArtifactPaths
from app.modules.strategy_service.services.storage_service import storage_service

# {section_name: [dotted-path field names to pull out of the report dict]}.
# A bare name is a top-level key of `report["report"]` (the validated
# BacktestReport dict); "metrics.xxx" pulls just that sub-key out of the
# nested `metrics` dict, keeping `metrics` itself intact per-section (so
# `overview["metrics"] = {"global": ..., "symbols": ...}`, not the whole
# thing duplicated into every section).
BACKTEST_SECTIONS: dict[str, list[str]] = {
    # Rendered outside the tabs too (masthead/warnings-banner data), and the
    # default/initial tab — needs to be available the moment the page loads.
    "overview": [
        "schema_version", "datasets", "dataset_health", "warnings",
        "fractional_kelly", "equity_curve",
        "metrics.global", "metrics.symbols",
    ],
    "analytics": [
        "correlations",
        "metrics.concentration", "metrics.diversification",
    ],
    "risk": [
        "monthly",
        "metrics.risk", "metrics.distributions", "metrics.capacity",
    ],
    # Trades & Execution and Monte Carlo tabs don't read report_payload at
    # all today (trades/orders are already separate Arrow datasets, and
    # Monte Carlo uses its own linked run's manifest) — no section needed.
}

# Optimization's report_payload (optimization_tasks.py:208-228) is already a
# flat dict, not nested under a "report" key — no dotted paths needed here.
# Configuration tab isn't listed: it renders from the separate `metadata`
# artifact (parameter_space/constraints/search_type/objective/dates), not
# report_payload at all (confirmed against ConfigurationPanel.tsx's actual
# props) — nothing to split out for it.
OPTIMIZATION_SECTIONS: dict[str, list[str]] = {
    "overview": ["best_result", "total_runs", "benchmark_return_pct", "optimization_health"],
    "leaderboard": ["leaderboard"],
    # all_results feeds the Parameter Heatmap (every tested combination, not
    # just the leaderboard) — belongs with the rest of the Parameters tab's
    # data, not Configuration.
    "parameters": ["parameter_sensitivity", "stability_region", "all_results"],
}

# Walkforward's report_payload nests everything under "report" (asdict of a
# WalkForwardReport — walkforward_tasks.py:184-188), same shape as backtest.
WALKFORWARD_SECTIONS: dict[str, list[str]] = {
    "overview": [
        "schema_version", "configuration", "summary", "aggregate_metrics",
        "robustness", "health", "coverage", "overfitting", "recommendation",
    ],
    # Equity tab is entirely dataset-driven already (useWalkforwardDataset
    # "equity"/"rolling") — no report_payload content needed.
    "windows": ["windows"],
    "regime": ["regime_summary"],
}

# Monte Carlo's report content (montecarlo_tasks.py, report_payload["report"]
# = asdict(MonteCarloReport)) is small aggregate stats, not row data, and
# several fields (summary/risk_analysis/probability) are read by BOTH the
# Overview tab (MonteCarloKpiStrip, ReturnDrawdownPanels) and the Probability
# tab (ProbabilityTable, MonteCarloRiskPanel) — splitting it further would
# mean fetching the same fields twice under different names. One section for
# the whole thing is the "don't over-split" call: Equity/Drawdown/
# Distributions/Simulations tabs are entirely dataset-driven already.
MONTECARLO_SECTIONS: dict[str, list[str]] = {
    "overview": [
        "schema_version", "configuration", "summary", "robustness",
        "risk_analysis", "recommendation", "percentiles", "probability",
        "health",
    ],
}

SECTION_MAPS: dict[str, dict[str, list[str]]] = {
    "BACKTEST": BACKTEST_SECTIONS,
    "OPTIMIZATION": OPTIMIZATION_SECTIONS,
    "WALKFORWARD": WALKFORWARD_SECTIONS,
    "MONTECARLO": MONTECARLO_SECTIONS,
}


def _extract(report: dict[str, Any], field_names: list[str]) -> dict[str, Any]:
    section: dict[str, Any] = {}
    for field_name in field_names:
        if "." not in field_name:
            if field_name in report:
                section[field_name] = report[field_name]
            continue
        top, sub = field_name.split(".", 1)
        top_value = report.get(top)
        if not isinstance(top_value, dict) or sub not in top_value:
            continue
        section.setdefault(top, {})[sub] = top_value[sub]
    return section


async def split_and_upload(
    paths: ArtifactPaths, run_type: str, report: dict[str, Any]
) -> dict[str, str]:
    """`report` is the dict actually holding the fields named in that run
    type's section map — `report_payload["report"]` for Backtest/Walkforward/
    Monte Carlo (which nest under a "report" key), or `report_payload`
    itself for Optimization (which is already flat). Returns
    {section_name: s3_key}, ready to merge into run.artifact_manifest."""
    section_map = SECTION_MAPS.get(run_type, {})

    keys: dict[str, str] = {}
    for name, field_names in section_map.items():
        section = _extract(report, field_names)
        if not section:
            continue
        key = paths.report_section(name)
        await storage_service.upload_msgpack_raw(key, section)
        keys[name] = key

    return keys
