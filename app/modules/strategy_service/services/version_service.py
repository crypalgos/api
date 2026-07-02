import hashlib
from datetime import datetime
import difflib
from sqlalchemy import func, select, update

from app.exceptions.exceptions import ResourceNotFoundException
from app.modules.strategy_service.models.strategy_version_model import StrategyVersion
from app.modules.strategy_service.models.research_note_model import ResearchNote
from app.modules.strategy_service.schema.strategy_schema import (
    StrategyVersionResponseSchema,
    VersionDiffResponseSchema,
    ResearchNoteResponseSchema,
    StrategyResponseSchema,
)


class VersionServiceMixin:
    async def _ensure_active_version(self, strategy) -> StrategyVersion:
        """
        Calculates the compiled hash of draft code.
        If has_unpublished_changes is True (or current_version is 0),
        creates a new StrategyVersion snapshot, increments current_version, and marks has_unpublished_changes = False.
        Otherwise, returns the StrategyVersion corresponding to current_version.
        """
        # Calculate compiled hash of current draft code
        if isinstance(strategy.compiled_code, str):
            code_bytes = strategy.compiled_code.encode("utf-8")
            current_hash = hashlib.sha256(code_bytes).hexdigest()
        else:
            current_hash = "mock_hash"
        strategy.compiled_hash = current_hash

        if not strategy.has_unpublished_changes and strategy.current_version > 0:
            # Look up existing version
            stmt = select(StrategyVersion).where(
                StrategyVersion.strategy_id == strategy.id,
                StrategyVersion.version == strategy.current_version,
            )
            res = await self.strategy_repository.session.execute(stmt)
            existing_version = res.scalar_one_or_none()
            if existing_version:
                return existing_version

        # Otherwise, create a new version snapshot
        # Find maximum version number for this strategy
        max_ver_stmt = select(func.max(StrategyVersion.version)).where(
            StrategyVersion.strategy_id == strategy.id
        )
        max_ver_res = await self.strategy_repository.session.execute(max_ver_stmt)
        max_ver = max_ver_res.scalar() or 0
        new_version = max_ver + 1

        new_snapshot = StrategyVersion(
            strategy_id=strategy.id,
            version=new_version,
            commit_message=f"Auto-snapshot before run version {new_version}",
            canvas_json=strategy.canvas_json,
            source_code=strategy.source_code,
            compiled_code=strategy.compiled_code,
            compiled_hash=current_hash,
            is_code_modified=strategy.is_code_modified,
        )
        self.strategy_repository.session.add(new_snapshot)
        await self.strategy_repository.session.flush()

        strategy.current_version = new_version
        strategy.has_unpublished_changes = False
        strategy.updated_at = datetime.utcnow()
        await self.strategy_repository.update(strategy.id)

        return new_snapshot

    async def save_version(
        self, user_id: str, strategy_id: str, commit_message: str | None
    ) -> tuple[int, StrategyVersionResponseSchema]:
        """Manually save a snapshot version of the strategy draft."""
        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        # Calculate compiled hash of current draft code
        if isinstance(strategy.compiled_code, str):
            code_bytes = strategy.compiled_code.encode("utf-8")
            current_hash = hashlib.sha256(code_bytes).hexdigest()
        else:
            current_hash = "mock_hash"
        strategy.compiled_hash = current_hash

        # Get max version
        max_ver_stmt = select(func.max(StrategyVersion.version)).where(
            StrategyVersion.strategy_id == strategy.id
        )
        max_ver_res = await self.strategy_repository.session.execute(max_ver_stmt)
        max_ver = max_ver_res.scalar() or 0
        new_version = max_ver + 1

        new_snapshot = StrategyVersion(
            strategy_id=strategy.id,
            version=new_version,
            commit_message=commit_message or f"Manual snapshot version {new_version}",
            canvas_json=strategy.canvas_json,
            source_code=strategy.source_code,
            compiled_code=strategy.compiled_code,
            compiled_hash=current_hash,
            is_code_modified=strategy.is_code_modified,
        )
        self.strategy_repository.session.add(new_snapshot)
        await self.strategy_repository.session.flush()

        strategy.current_version = new_version
        strategy.has_unpublished_changes = False
        strategy.updated_at = datetime.utcnow()
        await self.strategy_repository.update(strategy.id)

        return 201, StrategyVersionResponseSchema.model_validate(new_snapshot)

    async def list_versions(
        self, user_id: str, strategy_id: str
    ) -> tuple[int, list[StrategyVersionResponseSchema]]:
        """List version history of a strategy."""
        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        stmt = (
            select(StrategyVersion)
            .where(StrategyVersion.strategy_id == strategy_id)
            .order_by(StrategyVersion.version.desc())
        )
        res = await self.strategy_repository.session.execute(stmt)
        versions = res.scalars().all()
        return 200, [StrategyVersionResponseSchema.model_validate(v) for v in versions]

    async def get_version(
        self, user_id: str, strategy_id: str, version: int
    ) -> tuple[int, StrategyVersionResponseSchema]:
        """Fetch details of a specific strategy version."""
        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        stmt = select(StrategyVersion).where(
            StrategyVersion.strategy_id == strategy_id,
            StrategyVersion.version == version,
        )
        res = await self.strategy_repository.session.execute(stmt)
        snapshot = res.scalar_one_or_none()
        if not snapshot:
            raise ResourceNotFoundException("Version not found")
        return 200, StrategyVersionResponseSchema.model_validate(snapshot)

    async def restore_version(
        self, user_id: str, strategy_id: str, version: int
    ) -> tuple[int, StrategyResponseSchema]:
        """Restore a historical version snapshot into the current draft, setting has_unpublished_changes = True."""
        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        stmt = select(StrategyVersion).where(
            StrategyVersion.strategy_id == strategy_id,
            StrategyVersion.version == version,
        )
        res = await self.strategy_repository.session.execute(stmt)
        snapshot = res.scalar_one_or_none()
        if not snapshot:
            raise ResourceNotFoundException("Version not found")

        # Copy snapshot fields into the strategy draft
        strategy.canvas_json = snapshot.canvas_json or {}
        strategy.source_code = snapshot.source_code
        strategy.compiled_code = snapshot.compiled_code
        strategy.compiled_hash = snapshot.compiled_hash
        strategy.is_code_modified = snapshot.is_code_modified
        strategy.strategy_type = "CODE" if snapshot.is_code_modified else "VISUAL"

        # In restore workflow: retaining the active version index but setting has_unpublished_changes = True
        strategy.current_version = snapshot.version
        strategy.has_unpublished_changes = True
        strategy.updated_at = datetime.utcnow()

        updated_strategy = await self.strategy_repository.update(strategy.id)
        return 200, StrategyResponseSchema.model_validate(updated_strategy)

    async def diff_version(
        self, user_id: str, strategy_id: str, version: int
    ) -> tuple[int, VersionDiffResponseSchema]:
        """Compare a version snapshot against the current draft."""
        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        stmt = select(StrategyVersion).where(
            StrategyVersion.strategy_id == strategy_id,
            StrategyVersion.version == version,
        )
        res = await self.strategy_repository.session.execute(stmt)
        snapshot = res.scalar_one_or_none()
        if not snapshot:
            raise ResourceNotFoundException("Version not found")

        # Compute unified diff of compiled_code
        version_code_lines = snapshot.compiled_code.splitlines(keepends=True)
        draft_code_lines = strategy.compiled_code.splitlines(keepends=True)

        diff = difflib.unified_diff(
            version_code_lines,
            draft_code_lines,
            fromfile=f"version_{version}",
            tofile="draft",
        )
        diff_str = "".join(diff)

        # Check if canvas changed
        canvas_changed = snapshot.canvas_json != strategy.canvas_json

        return 200, VersionDiffResponseSchema(
            diff_code=diff_str, canvas_changed=canvas_changed
        )

    async def update_version_label(
        self, user_id: str, strategy_id: str, version: int, label: str | None
    ) -> tuple[int, StrategyVersionResponseSchema]:
        """Update label of a specific strategy version snapshot."""
        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        stmt = select(StrategyVersion).where(
            StrategyVersion.strategy_id == strategy_id,
            StrategyVersion.version == version,
        )
        res = await self.strategy_repository.session.execute(stmt)
        snapshot = res.scalar_one_or_none()
        if not snapshot:
            raise ResourceNotFoundException("Version not found")

        snapshot.label = label
        await self.strategy_repository.session.commit()
        return 200, StrategyVersionResponseSchema.model_validate(snapshot)

    async def update_version_approval(
        self, user_id: str, strategy_id: str, version: int, status: str
    ) -> tuple[int, StrategyVersionResponseSchema]:
        """Update approval status of a specific strategy version snapshot."""
        ALLOWED_STATUSES = {
            "DRAFT",
            "REVIEWING",
            "APPROVED",
            "REJECTED",
            "PAPER_TRADING",
            "LIVE",
        }
        status_upper = status.upper()
        if status_upper not in ALLOWED_STATUSES:
            raise ValueError(
                f"Invalid approval status. Must be one of: {ALLOWED_STATUSES}"
            )

        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        stmt = select(StrategyVersion).where(
            StrategyVersion.strategy_id == strategy_id,
            StrategyVersion.version == version,
        )
        res = await self.strategy_repository.session.execute(stmt)
        snapshot = res.scalar_one_or_none()
        if not snapshot:
            raise ResourceNotFoundException("Version not found")

        snapshot.approval_status = status_upper
        await self.strategy_repository.session.commit()
        return 200, StrategyVersionResponseSchema.model_validate(snapshot)

    async def set_golden_version(
        self, user_id: str, strategy_id: str, version: int
    ) -> tuple[int, StrategyVersionResponseSchema]:
        """Set a historical version snapshot as the golden candidate for the strategy."""
        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        if version <= 0:
            # If version is 0 or less, ensure an active version snapshot exists
            snapshot = await self._ensure_active_version(strategy)
        else:
            stmt = select(StrategyVersion).where(
                StrategyVersion.strategy_id == strategy_id,
                StrategyVersion.version == version,
            )
            res = await self.strategy_repository.session.execute(stmt)
            snapshot = res.scalar_one_or_none()
            if not snapshot:
                # Fallback to current version or create one
                snapshot = await self._ensure_active_version(strategy)

        if snapshot.is_golden:
            # Toggle off
            snapshot.is_golden = False
        else:
            # Reset all other versions of this strategy
            await self.strategy_repository.session.execute(
                update(StrategyVersion)
                .where(StrategyVersion.strategy_id == strategy_id)
                .values(is_golden=False)
            )
            snapshot.is_golden = True

        await self.strategy_repository.session.commit()
        return 200, StrategyVersionResponseSchema.model_validate(snapshot)

    async def create_research_note(
        self, user_id: str, strategy_id: str, content: str, run_id: str | None = None
    ) -> tuple[int, ResearchNoteResponseSchema]:
        """Create a new research note for a strategy (optionally linked to a run)."""
        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        if run_id:
            run = await self.run_repository.get_by_id(run_id)
            if not run or run.strategy_id != strategy_id:
                raise ResourceNotFoundException(
                    "Research run not found or does not belong to this strategy"
                )

        new_note = ResearchNote(strategy_id=strategy_id, run_id=run_id, content=content)
        self.strategy_repository.session.add(new_note)
        await self.strategy_repository.session.commit()
        return 201, ResearchNoteResponseSchema.model_validate(new_note)

    async def list_strategy_notes(
        self, user_id: str, strategy_id: str
    ) -> tuple[int, list[ResearchNoteResponseSchema]]:
        """List all research notes for a strategy."""
        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        stmt = (
            select(ResearchNote)
            .where(ResearchNote.strategy_id == strategy_id)
            .order_by(ResearchNote.created_at.desc())
        )
        res = await self.strategy_repository.session.execute(stmt)
        notes = res.scalars().all()
        return 200, [ResearchNoteResponseSchema.model_validate(n) for n in notes]

    async def list_run_notes(
        self, user_id: str, strategy_id: str, run_id: str
    ) -> tuple[int, list[ResearchNoteResponseSchema]]:
        """List all research notes for a specific run."""
        strategy = await self.strategy_repository.get_by_user_and_id(
            user_id, strategy_id
        )
        if not strategy or strategy.is_archived:
            raise ResourceNotFoundException("Strategy not found")

        run = await self.run_repository.get_by_id(run_id)
        if not run or run.strategy_id != strategy_id:
            raise ResourceNotFoundException("Research run not found")

        stmt = (
            select(ResearchNote)
            .where(
                ResearchNote.strategy_id == strategy_id, ResearchNote.run_id == run_id
            )
            .order_by(ResearchNote.created_at.desc())
        )
        res = await self.strategy_repository.session.execute(stmt)
        notes = res.scalars().all()
        return 200, [ResearchNoteResponseSchema.model_validate(n) for n in notes]
