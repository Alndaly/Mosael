"""Workflow edge cases that produced a wrong answer instead of an error."""

from __future__ import annotations

import pytest

from app.domain.workflows import interpolate, validate_body_graph, validate_graph
from app.domain.workflows.engine import LOOP_FOREACH_HARD_CAP


class TestMissingReference:
    """A typo'd reference used to resolve to {} — the sentinel used to walk dotted paths —
    which is truthy-ish in some places and falsy in others, so a mistake flipped behaviour
    rather than showing up."""

    def test_a_missing_reference_reads_as_empty(self) -> None:
        assert interpolate("{{typo}}", {}) == ""

    def test_a_missing_reference_does_not_leak_the_sentinel(self) -> None:
        # str({}) is non-empty, so `not_empty` on a typo'd operand evaluated TRUE and the
        # condition branch silently inverted.
        assert interpolate("{{typo}}", {"real": 1}) != "{}"

    def test_a_present_reference_still_resolves(self) -> None:
        assert interpolate("{{a.b}}", {"a": {"b": "x"}}) == "x"
        assert interpolate("{{a}}", {"a": "x"}) == "x"

    def test_a_missing_nested_key_still_reads_as_empty(self) -> None:
        assert interpolate("{{a.nope}}", {"a": {"b": "x"}}) == ""


class TestGraphShape:
    def test_a_non_dict_node_is_a_validation_error_not_a_crash(self) -> None:
        # Only the containers were type-checked, so this reached .get() and raised
        # AttributeError past the domain-error handler — a 500 for a plainly bad request.
        errors = validate_graph({"nodes": ["oops"], "edges": []})
        assert errors and any("对象" in e for e in errors)

    def test_a_non_dict_edge_is_a_validation_error(self) -> None:
        graph = {"nodes": [{"id": "start", "type": "start"}], "edges": ["nope"]}
        assert validate_graph(graph)

    def test_a_well_formed_graph_still_passes(self) -> None:
        assert validate_graph({"nodes": [{"id": "start", "type": "start"}], "edges": []}) == []


class TestLoopBodyScope:
    def _body(self, template: str) -> dict:
        return {
            "nodes": [{"id": "n1", "type": "code", "config": {"code": template}}],
            "edges": [],
        }

    def test_referencing_an_outer_node_is_rejected(self) -> None:
        """run_subgraph seeds the body with `loop` and the body's own nodes only, so this used
        to interpolate to the empty string — silently missing text in whatever the loop made."""
        errors = validate_body_graph(self._body("prefix = '{{start.prefix}}'"))
        assert errors and any("循环外" in e for e in errors)

    def test_loop_and_sibling_references_are_allowed(self) -> None:
        body = {
            "nodes": [
                {"id": "n1", "type": "code", "config": {"code": "x = '{{loop.item}}'"}},
                {"id": "n2", "type": "code", "config": {"code": "y = '{{n1.output}}'"}},
            ],
            "edges": [{"source": "n1", "target": "n2"}],
        }
        assert validate_body_graph(body) == []

    def test_an_empty_body_is_still_rejected_first(self) -> None:
        assert validate_body_graph({"nodes": [], "edges": []})


def test_foreach_is_capped_like_while() -> None:
    """`while` was clamped to 1000 and foreach was not, though its items can come from a code,
    http_request or json_extract node — that is, from remote data. Every iteration also
    accumulates a result, so an unbounded list is a memory problem before a time one."""
    assert LOOP_FOREACH_HARD_CAP == 1000


@pytest.mark.parametrize("value", ["{{loop.item}}", "{{n1.output}}", "no templates here"])
def test_body_validation_accepts_ordinary_templates(value: str) -> None:
    body = {"nodes": [{"id": "n1", "type": "code", "config": {"code": value}}], "edges": []}
    assert all("循环外" not in e for e in validate_body_graph(body))
