"""A start node is a start node whatever it is called."""

from __future__ import annotations

import inspect

from app.domain.workflows import engine, validate_graph


def _graph(start_id: str) -> dict:
    return {
        "nodes": [
            {"id": start_id, "type": "start", "config": {"params": {"who": "world"}}},
            {"id": "out", "type": "code", "config": {"code": "result = 1"}},
        ],
        "edges": [{"source": start_id, "target": "out"}],
    }


def test_a_start_node_with_a_custom_id_is_a_valid_graph() -> None:
    """Validation accepts it, which is half of why the engine skipping it was so quiet."""
    assert validate_graph(_graph("begin")) == []
    assert validate_graph(_graph("start")) == []


def test_the_engine_does_not_identify_the_start_node_by_its_id() -> None:
    """A source guard, not a behaviour test — running the real engine needs a job, a thread pool
    and a DB session, which is more machinery than this one-line invariant is worth.

    The invariant: the skip check must key on node TYPE. Keyed on the literal id "start", a
    start node named anything else had no incoming edges, failed the check and was skipped;
    every downstream node then saw no executed source and was skipped too — and the run still
    reported SUCCEEDED, with an empty context. A silent wrong answer, not a visible failure.
    run_node has always dispatched on type, so the two halves disagreed.
    """
    source = inspect.getsource(engine)
    assert 'nid != "start"' not in source, "the start node is being identified by id again"
    # 入口判定按类型(execute_graph.is_entry:start 类型永远是入口),不按字面 id。
    assert 'node_types.get(nid) == "start"' in source
