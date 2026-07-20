"""Workflow nodes that manage assets and projects.

Tagging, renaming and filing were things only a human could do through the UI, which made
"import a batch, tag it, file it under a project" a manual chore that a workflow should have
been able to own end to end.

The riskiest part is not the logic but the persistence: `tags` is a JSON column, and mutating
the list in place leaves SQLAlchemy seeing no change, so the write silently does nothing.
Every test here reads back from a fresh session for that reason.
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import Asset, Project, Workflow, Workspace
from app.domain.workflows import NODE_TYPES, WorkflowDomainError
from app.domain.workflows.engine import (
    _handle_asset_tag,
    _handle_asset_update,
    _handle_project_create,
    _id_list,
)
from tests.util import fresh_client


def _setup(tags: list[str] | None = None, count: int = 1):
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=workspace_id, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        assets = [Asset(workspace_id=workspace_id, name=f"a{i}", kind="video", tags=list(tags or [])) for i in range(count)]
        for asset in assets:
            db.add(asset)
        db.commit()
        return workflow.id, [asset.id for asset in assets], workspace_id


def _tags_of(asset_id: str) -> list[str]:
    with SessionLocal() as db:
        return list(db.get(Asset, asset_id).tags or [])


def _run(handler, workflow_id: str, config: dict):
    with SessionLocal() as db:
        return handler(db, db.get(Workflow, workflow_id), config)


class TestIdList:
    def test_a_comma_separated_string_is_split(self) -> None:
        assert _id_list("a, b ,c") == ["a", "b", "c"]

    def test_a_real_list_passes_through(self) -> None:
        """`{{查询.ids}}` resolves to the list asset_query produced. Stringifying it would
        match nothing, with no error to show for it."""
        assert _id_list(["a", "b"]) == ["a", "b"]

    def test_the_fullwidth_comma_chinese_keyboards_produce_is_handled(self) -> None:
        assert _id_list("a，b") == ["a", "b"]

    def test_blank_input_is_empty(self) -> None:
        assert _id_list("") == [] and _id_list(None) == []


class TestTagging:
    def test_add_appends_without_losing_existing_tags(self) -> None:
        workflow_id, [asset_id], _ = _setup(tags=["旧"])
        result = _run(_handle_asset_tag, workflow_id, {"asset_ids": asset_id, "tags": "新", "mode": "add"})
        assert result["count"] == 1
        assert _tags_of(asset_id) == ["旧", "新"]

    def test_add_does_not_duplicate(self) -> None:
        workflow_id, [asset_id], _ = _setup(tags=["旧"])
        _run(_handle_asset_tag, workflow_id, {"asset_ids": asset_id, "tags": "旧", "mode": "add"})
        assert _tags_of(asset_id) == ["旧"]

    def test_remove_takes_only_the_named_tags(self) -> None:
        workflow_id, [asset_id], _ = _setup(tags=["a", "b", "c"])
        _run(_handle_asset_tag, workflow_id, {"asset_ids": asset_id, "tags": "b", "mode": "remove"})
        assert _tags_of(asset_id) == ["a", "c"]

    def test_replace_swaps_the_whole_set(self) -> None:
        workflow_id, [asset_id], _ = _setup(tags=["a", "b"])
        _run(_handle_asset_tag, workflow_id, {"asset_ids": asset_id, "tags": "x", "mode": "replace"})
        assert _tags_of(asset_id) == ["x"]

    def test_replace_with_no_tags_clears_them(self) -> None:
        """The one case where empty tags is an instruction rather than a mistake."""
        workflow_id, [asset_id], _ = _setup(tags=["a"])
        _run(_handle_asset_tag, workflow_id, {"asset_ids": asset_id, "tags": "", "mode": "replace"})
        assert _tags_of(asset_id) == []

    def test_a_list_of_ids_from_asset_query_works(self) -> None:
        workflow_id, ids, _ = _setup(count=3)
        result = _run(_handle_asset_tag, workflow_id, {"asset_ids": ids, "tags": "批量", "mode": "add"})
        assert result["count"] == 3
        assert all(_tags_of(asset_id) == ["批量"] for asset_id in ids)

    def test_an_asset_from_another_workspace_is_skipped_not_written(self) -> None:
        """A hand-typed id must not reach across workspaces."""
        workflow_id, [mine], _ = _setup(tags=[])
        with SessionLocal() as db:
            elsewhere = Workspace(name="别人的工作区")
            db.add(elsewhere)
            db.commit()
            other = Asset(workspace_id=elsewhere.id, name="theirs", kind="video", tags=[])
            db.add(other)
            db.commit()
            other_id = other.id

        result = _run(_handle_asset_tag, workflow_id, {"asset_ids": [mine, other_id], "tags": "t", "mode": "add"})

        assert result["count"] == 1
        assert _tags_of(mine) == ["t"]
        assert _tags_of(other_id) == []

    def test_an_unknown_mode_is_refused(self) -> None:
        workflow_id, [asset_id], _ = _setup()
        with pytest.raises(WorkflowDomainError, match="模式"):
            _run(_handle_asset_tag, workflow_id, {"asset_ids": asset_id, "tags": "t", "mode": "nonsense"})

    def test_no_ids_is_an_error_rather_than_a_silent_no_op(self) -> None:
        """A workflow whose filter matched nothing should say so, not report success."""
        workflow_id, _, _ = _setup()
        with pytest.raises(WorkflowDomainError, match="素材 id"):
            _run(_handle_asset_tag, workflow_id, {"asset_ids": "", "tags": "t"})


class TestAssetUpdate:
    def test_a_single_asset_takes_the_name_verbatim(self) -> None:
        workflow_id, [asset_id], _ = _setup()
        _run(_handle_asset_update, workflow_id, {"asset_ids": asset_id, "name": "成片"})
        with SessionLocal() as db:
            assert db.get(Asset, asset_id).name == "成片"

    def test_several_assets_get_numbered(self) -> None:
        """One name across many assets produces N identical rows, unusable in a picker."""
        workflow_id, ids, _ = _setup(count=3)
        _run(_handle_asset_update, workflow_id, {"asset_ids": ids, "name": "成片"})
        with SessionLocal() as db:
            assert [db.get(Asset, i).name for i in ids] == ["成片 1", "成片 2", "成片 3"]

    def test_filing_under_a_project_sets_project_id(self) -> None:
        workflow_id, [asset_id], workspace_id = _setup()
        created = _run(_handle_project_create, workflow_id, {"name": "P"})
        _run(_handle_asset_update, workflow_id, {"asset_ids": asset_id, "project_id": created["project_id"]})
        with SessionLocal() as db:
            assert db.get(Asset, asset_id).project_id == created["project_id"]

    def test_a_project_from_another_workspace_is_refused(self) -> None:
        workflow_id, [asset_id], _ = _setup()
        with SessionLocal() as db:
            elsewhere = Workspace(name="别人的工作区")
            db.add(elsewhere)
            db.commit()
            stranger = Project(workspace_id=elsewhere.id, name="theirs")
            db.add(stranger)
            db.commit()
            stranger_id = stranger.id
        with pytest.raises(WorkflowDomainError, match="项目"):
            _run(_handle_asset_update, workflow_id, {"asset_ids": asset_id, "project_id": stranger_id})

    def test_changing_nothing_is_an_error(self) -> None:
        workflow_id, [asset_id], _ = _setup()
        with pytest.raises(WorkflowDomainError, match="新名称"):
            _run(_handle_asset_update, workflow_id, {"asset_ids": asset_id})


class TestProjectCreate:
    def test_it_returns_an_id_the_next_node_can_use(self) -> None:
        workflow_id, _, workspace_id = _setup()
        result = _run(_handle_project_create, workflow_id, {"name": "新项目"})
        with SessionLocal() as db:
            project = db.get(Project, result["project_id"])
            assert project.name == "新项目" and project.workspace_id == workspace_id

    def test_a_blank_name_is_refused(self) -> None:
        workflow_id, _, _ = _setup()
        with pytest.raises(WorkflowDomainError, match="项目名"):
            _run(_handle_project_create, workflow_id, {"name": "  "})


def test_every_new_node_type_is_registered_and_executable() -> None:
    """A type in the registry with no handler is offered in the palette and fails at run time."""
    from app.domain.workflows.engine import _HANDLERS

    for node_type in ("asset_tag", "asset_update", "project_create"):
        assert node_type in NODE_TYPES, f"{node_type} missing from the palette"
        assert node_type in _HANDLERS, f"{node_type} has no executor"
