"""Tests for obsidian_self_mcp.client — async CouchDB client with respx mocking."""

import pytest
import respx
from httpx import Response

from obsidian_self_mcp.client import ObsidianVaultClient
from obsidian_self_mcp.config import Config

BASE = "http://test:5984/test-vault"


@pytest.fixture
def config():
    return Config(
        couch_url="http://test:5984",
        couch_user="user",
        couch_pass="pass",
        db_name="test-vault",
    )


@pytest.fixture
def client(config):
    return ObsidianVaultClient(config)


def _make_parent_doc(doc_id, children, **kwargs):
    """Helper to build a CouchDB parent document."""
    doc = {
        "_id": doc_id,
        "_rev": "1-abc",
        "children": children,
        "type": "plain",
        "ctime": 1700000000000,
        "mtime": 1700000000000,
        "size": 100,
        "path": doc_id,
    }
    doc.update(kwargs)
    return doc


def _mock_get_doc(doc_id_encoded, doc):
    """Mock a successful GET for a document."""
    respx.get(f"{BASE}/{doc_id_encoded}").mock(
        return_value=Response(200, json=doc)
    )


def _mock_get_doc_404(doc_id_encoded):
    """Mock a 404 GET for a document."""
    respx.get(f"{BASE}/{doc_id_encoded}").mock(
        return_value=Response(404, json={"error": "not_found"})
    )


def _mock_all_docs(chunks: dict[str, str]):
    """Mock POST _all_docs returning chunk data."""
    rows = [{"id": cid, "doc": {"data": data}} for cid, data in chunks.items()]
    respx.post(f"{BASE}/_all_docs").mock(
        return_value=Response(200, json={"rows": rows})
    )


# ── _get_doc ──────────────────────────────────────────────────────


@respx.mock
async def test_get_doc_found(client):
    doc = _make_parent_doc("notes/todo.md", ["h:chunk1"])
    _mock_get_doc("notes%2Ftodo.md", doc)

    result = await client._get_doc("Notes/todo.md")
    assert result["_id"] == "notes/todo.md"


@respx.mock
async def test_get_doc_not_found(client):
    _mock_get_doc_404("notes%2Ftodo.md")
    _mock_get_doc_404("%2Fnotes%2Ftodo.md")

    result = await client._get_doc("Notes/todo.md")
    assert result is None


@respx.mock
async def test_get_doc_server_error_raises(client):
    respx.get(f"{BASE}/notes%2Ftodo.md").mock(
        return_value=Response(500, json={"error": "internal"})
    )
    with pytest.raises(Exception):
        await client._get_doc("Notes/todo.md")


@respx.mock
async def test_get_doc_underscore_prefix(client):
    """Paths starting with _ get / prefix for CouchDB."""
    doc = _make_parent_doc("/_changelog/entry.md", ["h:chunk1"])
    _mock_get_doc("%2F_changelog%2Fentry.md", doc)

    result = await client._get_doc("_Changelog/entry.md")
    assert result is not None


# ── read_note ─────────────────────────────────────────────────────


@respx.mock
async def test_read_note_single_chunk(client):
    doc = _make_parent_doc("notes/todo.md", ["h:abcdefghijkl"], size=12)
    _mock_get_doc("notes%2Ftodo.md", doc)
    _mock_all_docs({"h:abcdefghijkl": "Hello world!"})

    result = await client.read_note("Notes/todo.md")
    assert result is not None
    assert result.content == "Hello world!"
    assert result.path == "notes/todo.md"
    assert result.is_binary is False


@respx.mock
async def test_read_note_multiple_chunks(client):
    doc = _make_parent_doc("notes/long.md", ["h:chunk1aaaaaa", "h:chunk2bbbbbb"])
    _mock_get_doc("notes%2Flong.md", doc)
    _mock_all_docs({"h:chunk1aaaaaa": "First part. ", "h:chunk2bbbbbb": "Second part."})

    result = await client.read_note("Notes/long.md")
    assert result.content == "First part. Second part."


@respx.mock
async def test_read_note_not_found(client):
    _mock_get_doc_404("notes%2Fmissing.md")
    _mock_get_doc_404("%2Fnotes%2Fmissing.md")

    result = await client.read_note("Notes/missing.md")
    assert result is None


@respx.mock
async def test_read_note_missing_chunk_raises(client):
    doc = _make_parent_doc("notes/todo.md", ["h:exists00000", "h:missing00000"])
    _mock_get_doc("notes%2Ftodo.md", doc)
    # Only return one of the two chunks
    _mock_all_docs({"h:exists00000": "partial"})

    with pytest.raises(ValueError, match="Missing 1 chunk"):
        await client.read_note("Notes/todo.md")


@respx.mock
async def test_read_note_binary(client):
    doc = _make_parent_doc("img/photo.png", ["h:binchunk0000"], type="newnote")
    _mock_get_doc("img%2Fphoto.png", doc)
    _mock_all_docs({"h:binchunk0000": "aGVsbG8="})

    result = await client.read_note("img/photo.png")
    assert result.is_binary is True


# ── write_note ────────────────────────────────────────────────────


@respx.mock
async def test_write_note_new(client):
    # No existing doc
    _mock_get_doc_404("notes%2Fnew.md")
    _mock_get_doc_404("%2Fnotes%2Fnew.md")

    # Chunk creation
    respx.put(url__regex=rf"{BASE}/h%3A.*").mock(
        return_value=Response(201, json={"ok": True, "rev": "1-new"})
    )
    # Parent doc creation
    respx.put(f"{BASE}/notes%2Fnew.md").mock(
        return_value=Response(201, json={"ok": True, "rev": "1-doc"})
    )

    result = await client.write_note("Notes/new.md", "# New Note")
    assert result is True


@respx.mock
async def test_write_note_update_existing(client):
    existing = _make_parent_doc("notes/todo.md", ["h:oldchunk0000"])
    _mock_get_doc("notes%2Ftodo.md", existing)

    # Chunk creation
    respx.put(url__regex=rf"{BASE}/h%3A.*").mock(
        return_value=Response(201, json={"ok": True, "rev": "1-new"})
    )
    # Parent doc update
    respx.put(f"{BASE}/notes%2Ftodo.md").mock(
        return_value=Response(200, json={"ok": True, "rev": "2-updated"})
    )

    result = await client.write_note("Notes/todo.md", "Updated content")
    assert result is True


# ── append_note ───────────────────────────────────────────────────


@respx.mock
async def test_append_note(client):
    doc = _make_parent_doc("notes/log.md", ["h:lastchunk000"])
    _mock_get_doc("notes%2Flog.md", doc)
    _mock_all_docs({"h:lastchunk000": "existing content"})

    # New chunk creation
    respx.put(url__regex=rf"{BASE}/h%3A.*").mock(
        return_value=Response(201, json={"ok": True, "rev": "1-new"})
    )
    # Parent doc update
    respx.put(f"{BASE}/notes%2Flog.md").mock(
        return_value=Response(200, json={"ok": True, "rev": "2-appended"})
    )

    result = await client.append_note("Notes/log.md", " appended")
    assert result is True


@respx.mock
async def test_append_note_not_found(client):
    _mock_get_doc_404("notes%2Fmissing.md")
    _mock_get_doc_404("%2Fnotes%2Fmissing.md")

    with pytest.raises(ValueError, match="Note not found"):
        await client.append_note("Notes/missing.md", "content")


@respx.mock
async def test_append_note_missing_last_chunk(client):
    doc = _make_parent_doc("notes/log.md", ["h:lastchunk000"])
    _mock_get_doc("notes%2Flog.md", doc)
    _mock_all_docs({})  # No chunks returned

    with pytest.raises(ValueError, match="Last chunk missing"):
        await client.append_note("Notes/log.md", " appended")


# ── delete_note ───────────────────────────────────────────────────


@respx.mock
async def test_delete_note(client):
    doc = _make_parent_doc("notes/old.md", ["h:chunk1aaaaaa"])
    _mock_get_doc("notes%2Fold.md", doc)

    # Chunk GET for rev
    respx.get(f"{BASE}/h%3Achunk1aaaaaa").mock(
        return_value=Response(200, json={"_id": "h:chunk1aaaaaa", "_rev": "1-chk"})
    )
    # Chunk DELETE
    respx.delete(f"{BASE}/h%3Achunk1aaaaaa").mock(
        return_value=Response(200, json={"ok": True})
    )
    # Parent DELETE
    respx.delete(f"{BASE}/notes%2Fold.md").mock(
        return_value=Response(200, json={"ok": True})
    )

    result = await client.delete_note("Notes/old.md")
    assert result is True


@respx.mock
async def test_delete_note_not_found(client):
    _mock_get_doc_404("notes%2Fmissing.md")
    _mock_get_doc_404("%2Fnotes%2Fmissing.md")

    with pytest.raises(ValueError, match="Note not found"):
        await client.delete_note("Notes/missing.md")


# ── search_notes ──────────────────────────────────────────────────


@respx.mock
async def test_search_notes(client):
    parent_doc = _make_parent_doc(
        "notes/todo.md", ["h:searchchunk0"], path="Notes/todo.md"
    )

    # _get_all_file_docs mock (two range queries)
    respx.get(f"{BASE}/_all_docs").mock(side_effect=[
        Response(200, json={"rows": [{"doc": parent_doc}]}),
        Response(200, json={"rows": []}),
    ])

    # Mango search
    respx.post(f"{BASE}/_find").mock(
        return_value=Response(200, json={
            "docs": [{"_id": "h:searchchunk0", "data": "Buy milk and eggs"}]
        })
    )

    results = await client.search_notes("milk")
    assert len(results) == 1
    assert results[0].path == "Notes/todo.md"
    assert results[0].matches == 1


@respx.mock
async def test_search_notes_no_results(client):
    respx.get(f"{BASE}/_all_docs").mock(side_effect=[
        Response(200, json={"rows": []}),
        Response(200, json={"rows": []}),
    ])
    respx.post(f"{BASE}/_find").mock(
        return_value=Response(200, json={"docs": []})
    )

    results = await client.search_notes("nonexistent")
    assert results == []


# ── _read_note_content ────────────────────────────────────────────


@respx.mock
async def test_read_note_content_missing_chunk_returns_none(client):
    """_read_note_content logs warning and returns None on missing chunks."""
    doc = {"_id": "notes/broken.md", "children": ["h:missing00000"]}
    _mock_all_docs({})  # No chunks

    result = await client._read_note_content(doc)
    assert result is None


# ── list_folders ──────────────────────────────────────────────────


@respx.mock
async def test_list_folders(client):
    docs = [
        _make_parent_doc("notes/a.md", ["h:c1"], path="Notes/a.md"),
        _make_parent_doc("notes/b.md", ["h:c2"], path="Notes/b.md"),
        _make_parent_doc("dev/c.md", ["h:c3"], path="Dev/c.md"),
    ]
    respx.get(f"{BASE}/_all_docs").mock(side_effect=[
        Response(200, json={"rows": [{"doc": d} for d in docs]}),
        Response(200, json={"rows": []}),
    ])

    folders = await client.list_folders()
    paths = [f.path for f in folders]
    assert "Dev" in paths
    assert "Notes" in paths


# ── frontmatter operations ────────────────────────────────────────


@respx.mock
async def test_read_frontmatter(client):
    content = "---\ntitle: Test\nstatus: draft\n---\nBody"
    doc = _make_parent_doc("notes/fm.md", ["h:fmchunk00000"])
    _mock_get_doc("notes%2Ffm.md", doc)
    _mock_all_docs({"h:fmchunk00000": content})

    fm = await client.read_frontmatter("Notes/fm.md")
    assert fm == {"title": "Test", "status": "draft"}


@respx.mock
async def test_read_frontmatter_none(client):
    doc = _make_parent_doc("notes/plain.md", ["h:plainchunk00"])
    _mock_get_doc("notes%2Fplain.md", doc)
    _mock_all_docs({"h:plainchunk00": "No frontmatter"})

    fm = await client.read_frontmatter("Notes/plain.md")
    assert fm is None
