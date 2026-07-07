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
    kind: str = "backtests"  # backtests | walkforwards | montecarlos | optimizations

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

    def montecarlo_dataset(self, name: str) -> str:
        """Chart datasets referenced by MonteCarloReport.charts[*].dataset —
        crypalgos_core.montecarlo.reporting.build_montecarlo_report() writes
        these as flat Arrow IPC files (not bundled in a workspace archive)."""
        return f"{self.base}/datasets/montecarlo/{name}.arrow"
