"""
ArtifactPaths — single source of truth for the S3 key layout of research
artifacts. Writers (tasks) and readers (replay, dashboards) must both resolve
keys through this; never format `research/...` strings inline.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactPaths:
    strategy_id: str
    run_id: str
    kind: str = "backtests"  # backtests | walkforwards | montecarlos | optimizations | live-sessions

    @property
    def base(self) -> str:
        return f"research/{self.strategy_id}/{self.kind}/{self.run_id}"

    @property
    def metadata(self) -> str:
        return f"{self.base}/metadata.msgpack.zstd"

    @property
    def report(self) -> str:
        return f"{self.base}/report.msgpack.zstd"

    @property
    def workspace(self) -> str:
        return f"{self.base}/workspace.tar.zstd"

    @property
    def runtime(self) -> str:
        return f"{self.base}/runtime.arrow.zstd"

    @property
    def decision(self) -> str:
        return f"{self.base}/decision.arrow.zstd"

    def report_section(self, name: str, version: int = 1) -> str:
        """Small scalar/summary report sections (KPI strips, risk stat cells,
        configuration, distribution summaries) — msgpack only, no zstd (see
        report_split.py). Versioned path segment lets a future change to a
        section's content shape ship as v2 without touching runs that already
        wrote v1 — their artifact_manifest keeps pointing at the v1 key."""
        return f"{self.base}/sections/v{version}/{name}.msgpack"

    def report_section_arrow(self, name: str, version: int = 1) -> str:
        """Row/table-shaped report sections (leaderboard rows, optimization
        all_results, walkforward per-window rollups) that don't already have
        a dedicated dataset method below — Arrow IPC, same versioning as
        report_section()."""
        return f"{self.base}/sections/v{version}/{name}.arrow"

    def montecarlo_dataset(self, name: str) -> str:
        """Chart datasets referenced by MonteCarloReport.charts[*].dataset —
        crypalgos_core.montecarlo.reporting.build_montecarlo_report() writes
        these as flat Arrow IPC files (not bundled in a workspace archive)."""
        return f"{self.base}/datasets/montecarlo/{name}.arrow"

    @property
    def live_candles(self) -> str:
        """kind='live-sessions', run_id=session_id. Same parquet file
        SessionWorkspaceArchive writes locally — uploaded as-is, no re-encode."""
        return f"{self.base}/candles.parquet"

    @property
    def live_events(self) -> str:
        return f"{self.base}/strategy_events.msgpack"

    @property
    def live_session_metadata(self) -> str:
        return f"{self.base}/session.json"

    def walkforward_dataset(self, name: str) -> str:
        """Chart datasets referenced by WalkForwardReport.charts[*].dataset —
        crypalgos_core.walkforward.reporting.build_walkforward_report() writes
        these as flat Arrow IPC files: equity.arrow, rolling.arrow, and one
        window_{id}_train.arrow / window_{id}_validation.arrow pair per
        window (dynamic per-window names, not a small fixed set — see
        data_service.py's pattern validation, not an exact-name allowlist)."""
        return f"{self.base}/datasets/walkforward/{name}.arrow"
