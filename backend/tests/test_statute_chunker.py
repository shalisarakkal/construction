from app.chunkers.statute import looks_like_statute, statute_chunk


def test_looks_like_statute_true_for_lexis_boilerplate():
    text = "N.J. Stat. § 52:27D-119\nLexisNexis® New Jersey Annotated Statutes > Title 52.\nSome text."
    assert looks_like_statute(text) is True


def test_looks_like_statute_false_for_unrelated_text():
    assert looks_like_statute("This is a generic engineering memo about foundations.") is False


def test_statute_chunk_simple_section_produces_one_chunk():
    text = (
        "N.J. Stat. § 52:27D-120\n\n"
        "§ 52:27D-120. Purpose\n"
        "This act is intended to protect the health, safety and welfare of the people of this State.\n"
        "End of Document"
    )

    chunks = statute_chunk("doc1", text)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk["citation"] == "N.J. Stat. § 52:27D-120"
    assert chunk["section_title"] == "Purpose"
    assert chunk["chunk_type"] == "statute_section"
    assert "protect the health, safety and welfare" in chunk["text"]


def test_statute_chunk_strips_page_boilerplate_and_breadcrumb():
    text = (
        "N.J. Stat. § 52:27D-120\n"
        "Current through New Jersey 221st Second Annual Session, L. 2025, c. 152 and J.R. 11\n"
        "LexisNexis® New Jersey Annotated Statutes > Title 52. State Government > Chapter 27D.\n"
        "§ 52:27D-120. Purpose\n"
        "This act is intended to protect the health, safety and welfare of the people of this State.\n"
        "End of Document"
    )

    chunks = statute_chunk("doc1", text)

    assert len(chunks) == 1
    text_out = chunks[0]["text"]
    assert "LexisNexis" not in text_out
    assert "Current through" not in text_out


def test_statute_chunk_splits_on_lettered_subsections():
    filler = " ".join(["requirement"] * 300)
    text = (
        "N.J. Stat. § 52:27D-121\n\n"
        "§ 52:27D-121. Definitions\n"
        f"a. {filler}\n"
        f"b. {filler}\n"
        "End of Document"
    )

    chunks = statute_chunk("doc1", text)

    assert [c["citation"] for c in chunks] == [
        "N.J. Stat. § 52:27D-121(a)",
        "N.J. Stat. § 52:27D-121(b)",
    ]
    assert all(c["word_count"] <= 500 for c in chunks)


def test_statute_chunk_splits_on_numbered_sub_items():
    item = " ".join(["item"] * 200)
    text = (
        "N.J. Stat. § 52:27D-122\n\n"
        "§ 52:27D-122. Numbered section\n"
        f"a.\n(1) {item}\n(2) {item}\n(3) {item}\n"
        "End of Document"
    )

    chunks = statute_chunk("doc1", text)

    citations = [c["citation"] for c in chunks]
    # "a." itself counts as leading text ahead of item (1), same as njac's
    # letter-marker behavior -- so item 1 merges as ".1+".
    assert citations == [
        "N.J. Stat. § 52:27D-122(a).1+",
        "N.J. Stat. § 52:27D-122(a).2",
        "N.J. Stat. § 52:27D-122(a).3",
    ]
    assert all(c["word_count"] <= 500 for c in chunks)


def test_statute_chunk_indexes_history_as_a_separate_chunk_and_drops_annotations():
    # Annotations (case-law digest) is deliberately dropped entirely here,
    # not indexed separately like History -- see statute.py's module
    # docstring: this is the concrete fix for the retrieval-pollution
    # finding (a pure-annotation chunk ranked in real query results).
    text = (
        "N.J. Stat. § 52:27D-131\n\n"
        "§ 52:27D-131. Construction permits\n"
        "The enforcing agency shall examine each application for a construction permit.\n"
        "History\n"
        "L. 1975, c. 217, § 13; amended 2001, c. 457, § 1.\n"
        "Annotations\n"
        "CASE NOTES\n"
        "Governments: Local Governments: Licenses\n"
        "Some case summary text about a construction permit dispute goes here.\n"
        "LexisNexis® New Jersey Annotated Statutes\n"
        "Copyright © 2026 All rights reserved.\n"
        "End of Document"
    )

    chunks = statute_chunk("doc1", text)

    section = next(c for c in chunks if c["chunk_type"] == "statute_section")
    history = next(c for c in chunks if c["chunk_type"] == "statute_history")

    assert "examine each application" in section["text"]
    assert "Annotations" not in section["text"]
    assert "case summary" not in section["text"]

    assert "L. 1975, c. 217" in history["text"]
    assert history["citation"] == "N.J. Stat. § 52:27D-131 History"
    assert "Annotations" not in history["text"]
    assert "case summary" not in history["text"]
    assert "Copyright" not in history["text"]

    # No third chunk carrying the dropped annotation content.
    assert len(chunks) == 2


def test_statute_chunk_strips_trailing_copyright_footer_when_no_annotations_block():
    # Regression test: found live -- a section with no "Annotations" block
    # at all still has a trailing LexisNexis/copyright footer with no
    # "Annotations" label ahead of it to trigger the usual stripping. Would
    # otherwise leak into the History chunk (e.g. real corpus section
    # 52:27D-122.1). See statute.py's PAGE_BOILERPLATE_PATTERNS.
    text = (
        "N.J. Stat. § 52:27D-122.1\n\n"
        "§ 52:27D-122.1. Minor provision\n"
        "This section has a brief operative requirement.\n"
        "History\n"
        "L. 1996, c. 53, § 1.\n"
        "LexisNexis® New Jersey Annotated Statutes\n"
        "Copyright © 2026 All rights reserved.\n"
        "End of Document"
    )

    chunks = statute_chunk("doc1", text)

    history = next(c for c in chunks if c["chunk_type"] == "statute_history")
    assert "L. 1996, c. 53" in history["text"]
    assert "LexisNexis" not in history["text"]
    assert "Copyright" not in history["text"]
