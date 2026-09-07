"""Knowledge workflows and pinned canvas references stay scoped and reproducible."""
import pytest
from app.core.db import SessionLocal
from app.db.models import Note, Workflow
from app.domain.workflows import WorkflowDomainError, validate_graph
from app.domain.workflows.engine import execute_graph
from app.domain.workflows.executors.knowledge import note_read, note_search, note_create
from tests.util import fresh_client


def setup():
    client = fresh_client()
    ws = client.post('/api/workspaces', json={'name': 'Notes QA'}).json()['id']
    other = client.post('/api/workspaces', json={'name': 'Other'}).json()['id']
    note = client.post('/api/notes', json={'workspace_id': ws, 'title': '品牌规范', 'markdown': '# 品牌\n\n蓝色 100% 原文', 'tags': ['色彩']}).json()
    with SessionLocal() as db:
        wf = Workflow(workspace_id=ws, name='知识引用', graph={'nodes': [], 'edges': []})
        db.add(wf); db.commit(); wid = wf.id
    return client, ws, other, note, wid


def test_read_current_and_pinned_revision_and_citations():
    client, ws, _, note, wid = setup()
    changed = client.patch('/api/notes/'+note['id'], json={**note, 'base_revision': 1, 'markdown': '新版内容'}).json()
    assert changed['revision'] == 2
    with SessionLocal() as db:
        wf = db.get(Workflow, wid)
        old = note_read(db, wf, {'note_id': note['id'], 'revision': 1})
        assert old['text'] == note['markdown'] and old['markdown'] == old['text']
        assert old['citation_url'].endswith('&revision=1')
        assert note_read(db, wf, {'note_id': note['id']})['text'] == '新版内容'
        with pytest.raises(WorkflowDomainError): note_read(db, wf, {'note_id': note['id'], 'revision': 999})


def test_search_literal_pagination_and_workspace_trash_boundaries():
    client, ws, other, note, wid = setup()
    foreign = client.post('/api/notes', json={'workspace_id': other, 'title': '品牌规范', 'markdown': '私密'}).json()
    removed = client.post('/api/notes', json={'workspace_id': ws, 'title': '品牌旧稿', 'markdown': '旧稿', 'trashed': True}).json()
    with SessionLocal() as db:
        wf = db.get(Workflow, wid)
        assert note_search(db, wf, {'query': '%'})['ids'] == [note['id']]
        assert note_search(db, wf, {'query': '色彩'})['ids'] == [note['id']]
        assert note_search(db, wf, {'query': '品牌'})['count'] == 1
        assert note_search(db, wf, {'query': '不存在'})['count'] == 0
        for nid in [foreign['id'], removed['id']]:
            with pytest.raises(WorkflowDomainError): note_read(db, wf, {'note_id': nid})
        note_create(db, wf, {'title': '第二篇', 'markdown': '完整正文', 'tags': '参考，色彩'})
        first = note_search(db, wf, {'limit': 1})
        second = note_search(db, wf, {'limit': 1, 'offset': 1})
        assert first['has_more'] and not second['has_more']
        assert set(first['ids'] + second['ids']) == set(note_search(db, wf, {})['ids'])
        assert db.get(Note, first['ids'][0]).tags == ['参考', '色彩']
    assert client.get(f"/api/notes/{foreign['id']}/reference", params={'workspace_id': ws}).status_code == 404
    assert client.get(f"/api/notes/{removed['id']}/reference", params={'workspace_id': ws}).status_code == 409


def test_read_to_save_graph_passes_full_content_without_model():
    _, ws, _, note, wid = setup()
    graph = {'nodes': [
        {'id': 'start', 'type': 'start', 'config': {}},
        {'id': 'source', 'type': 'note_read', 'config': {'note_id': note['id']}},
        {'id': 'save', 'type': 'note_create', 'config': {'title': '工作流成稿', 'markdown': '{{source.text}}'}},
    ], 'edges': [{'id': 'a', 'source': 'start', 'target': 'source'}, {'id': 'b', 'source': 'source', 'target': 'save'}]}
    assert validate_graph(graph) == []
    context, cancelled = execute_graph(graph, wf_id=wid)
    assert not cancelled
    with SessionLocal() as db:
        saved = db.get(Note, context['save']['note_id'])
        assert saved.workspace_id == ws and saved.markdown == note['markdown']
        assert saved.id != note['id'] and db.get(Note, note['id']).revision == 1


def test_board_pin_survives_source_updates_and_handles_deleted_source():
    client, ws, other, note, _ = setup()
    item = {'id': 'doc', 'kind': 'document', 'x': 0, 'y': 0, 'note_id': note['id'], 'note_revision': 1}
    payload = {'workspace_id': ws, 'name': '参考文档', 'canvas': {'items': [item], 'edges': []}}
    board = client.post('/api/boards', json=payload).json()
    assert board['canvas']['items'][0]['text'] == note['title']
    assert client.post('/api/boards', json={**payload, 'workspace_id': other}).status_code == 400
    bad = {**item, 'note_revision': True}
    assert client.post('/api/boards', json={**payload, 'canvas': {'items': [bad]}}).status_code == 400
    trash = client.patch('/api/notes/'+note['id'], json={**note, 'base_revision': 1, 'trashed': True}).json()
    client.delete('/api/notes/'+note['id'], params={'workspace_id': ws, 'base_revision': trash['revision']})
    assert client.get(f"/api/notes/{note['id']}/reference", params={'workspace_id': ws, 'revision': 1}).status_code == 404
    moved = {**item, 'x': 120}
    result = client.patch('/api/boards/'+board['id'], json={**payload, 'base_revision': board['revision'], 'canvas': {'items': [moved], 'edges': []}})
    assert result.status_code == 200, result.text
    assert client.post('/api/boards', json=payload).status_code == 400
