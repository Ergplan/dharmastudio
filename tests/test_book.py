"""The bundled book: structure, text quality, and the idempotent import."""

import pytest

from backend import book_seed

# the book is never committed (public repo); these run where the author's local dev copy exists
pytestmark = pytest.mark.skipif(not book_seed.book_json_path().exists(), reason="no local copy of the book")


def test_book_structure():
    b = book_seed.book()
    kinds = [e["kind"] for e in b["entries"]]
    assert kinds.count("chapter") == 54 and kinds.count("interlude") == 6
    assert kinds[0] == "prologue" and "epilogue" in kinds and kinds[-1] == "glossary"
    assert sum(e["words"] for e in b["entries"]) > 55000
    ch1 = next(e for e in b["entries"] if e["kind"] == "chapter" and e["number"] == 1)
    assert ch1["paragraphs"][0] == "Lanka burned like a mountain of embers."
    assert {c["name"] for c in ch1["cast"]} >= {"Rama", "Ravana", "Vibhishana"}
    assert all(e["scene_settings"] for e in b["entries"] if e["kind"] != "glossary")
    nine = next(e for e in b["entries"] if e["kind"] == "chapter" and e["number"] == 9)
    assert nine["title"] == "फल"


def test_comic_chapters_cover_all_three_books():
    cs = book_seed.comic_chapters()
    assert len(cs) == 61 and cs[0]["title"] == "The Last Night of Lanka" and cs[0]["pages"] == [9, 15]
    assert {c["volume"] for c in cs} == {1, 2, 3}
    for v in (1, 2, 3):
        nums = [c["number"] for c in cs if c["volume"] == v]
        assert nums == list(range(1, len(nums) + 1))


def test_import_is_idempotent_and_keeps_chapter_one(client):
    from backend import db

    with db.session_scope() as s:
        first = book_seed.ensure(s)
    with db.session_scope() as s:
        again = book_seed.ensure(s)
    assert again["created"] == 0
    chapters = client.get("/api/chapters").json()
    assert len(chapters) >= 61
    pages = client.get("/api/pages", params={"chapter_id": 1}).json()
    assert len(pages) == 10 and sum(len(p["panels"]) for p in pages) == 32
    assert first["created"] + first["updated"] >= 61
