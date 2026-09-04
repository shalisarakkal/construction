from app.chunkers.generic import chunk_page, generic_chunk, split_sentences
from app.chunkers.njac import _dedupe_chunk_ids, looks_like_njac, njac_chunk

# ---------------------------------------------------------------------------
# njac.py
# ---------------------------------------------------------------------------


def test_looks_like_njac_true_for_njac_boilerplate():
    assert looks_like_njac("N.J.A.C. 5:23-1.1 Scope\nSome regulation text.") is True


def test_looks_like_njac_false_for_unrelated_text():
    assert looks_like_njac("This is a generic engineering memo about foundations.") is False


def test_njac_chunk_simple_section_produces_one_chunk():
    text = (
        "N.J.A.C. 5:23-1.1\n\n"
        "§ 5:23-1.1 Scope\n"
        "This subchapter applies to all buildings within the state.\n"
        "End of Document"
    )

    chunks = njac_chunk("doc1", text)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk["citation"] == "N.J.A.C. 5:23-1.1"
    assert chunk["section_title"] == "Scope"
    assert chunk["chunk_type"] == "njac_section"
    assert chunk["chunk_id"] == "doc1__5:23-1.1"
    assert "This subchapter applies to all buildings" in chunk["text"]


def test_njac_chunk_returns_empty_for_section_with_no_heading():
    # Mirrors a real placeholder/reserved subchapter (e.g. njac_5_23_4B_C.pdf:
    # "SUBCHAPTERS 4B AND 4C. (RESERVED)") -- passes looks_like_njac's sniff
    # but has no "§ X.Y Title" heading to chunk on, so ingestion.py falls
    # back to the generic chunker for text like this.
    text = "N.J.A.C. 5:23-4B\nSUBCHAPTERS 4B AND 4C. (RESERVED)\nEnd of Document"

    assert njac_chunk("doc1", text) == []


def test_njac_chunk_splits_oversized_section_on_lettered_subsections():
    filler = " ".join(["requirement"] * 300)
    text = (
        "N.J.A.C. 5:23-2.1\n\n"
        "§ 5:23-2.1 Big Section\n"
        f"(a) {filler}\n"
        f"(b) {filler}\n"
        "End of Document"
    )

    chunks = njac_chunk("doc1", text)

    assert [c["citation"] for c in chunks] == ["N.J.A.C. 5:23-2.1(a)", "N.J.A.C. 5:23-2.1(b)"]
    assert all(c["chunk_type"] == "njac_section" for c in chunks)
    assert all(c["word_count"] <= 500 for c in chunks)


def test_njac_chunk_gives_each_substantial_numbered_item_its_own_chunk():
    # Each item here (200 words) is well above MIN_GROUP_WORDS, so each gets
    # its own chunk rather than being merged with its neighbors -- merging
    # substantial, topically-independent items dilutes their embeddings (see
    # MIN_GROUP_WORDS's docstring in app/chunkers/njac.py for the real-world
    # finding that motivated this). "intro text." ahead of item 1 merges into
    # item 1's chunk (hence ".1+") rather than being dropped -- see
    # _split_on's leading-piece handling, also fixed alongside MIN_GROUP_WORDS.
    item = " ".join(["item"] * 200)
    text = (
        "N.J.A.C. 5:23-2.2\n\n"
        "§ 5:23-2.2 Numbered Section\n"
        f"(a) intro text.\n1. {item}\n2. {item}\n3. {item}\n"
        "End of Document"
    )

    chunks = njac_chunk("doc1", text)

    assert [c["citation"] for c in chunks] == [
        "N.J.A.C. 5:23-2.2(a).1+",
        "N.J.A.C. 5:23-2.2(a).2",
        "N.J.A.C. 5:23-2.2(a).3",
    ]
    assert "intro text" in chunks[0]["text"]
    assert all(c["word_count"] <= 500 for c in chunks)


def test_split_on_preserves_text_before_first_match():
    # Regression test: _split_on() used to silently drop any text before the
    # first regex match entirely (confirmed as real content loss on the live
    # corpus -- njac_5_23_2.pdf's actual "(b) The following are exceptions
    # from (a) above:" intro sentence was missing from the ingested chunk).
    from app.chunkers.njac import NUMBERED_SUB_RE, _split_on

    pieces = _split_on(NUMBERED_SUB_RE, "The following are exceptions:\n1. First.\n2. Second.")

    assert pieces == ["The following are exceptions:", "1. First.", "2. Second."]


def test_njac_chunk_still_groups_genuinely_tiny_numbered_items():
    # Items below MIN_GROUP_WORDS (e.g. a short "Addition of rope
    # equalizers"-style line) are too context-free to embed usefully alone,
    # so they should still be merged with their neighbors up to
    # MIN_GROUP_WORDS -- this is the original motivating case for grouping
    # at all (see NJ/eval/chunking_strategy.md section 4.2).
    filler = " ".join(["requirement"] * 600)  # forces the lettered piece to split further
    text = (
        "N.J.A.C. 5:23-2.3\n\n"
        "§ 5:23-2.3 Tiny Items Section\n"
        f"(a) {filler}\n"
        "1. short one.\n2. short two.\n3. short three.\n4. short four.\n"
        "End of Document"
    )

    chunks = njac_chunk("doc1", text)

    citations = [c["citation"] for c in chunks]
    # The oversized intro paragraph is its own chunk; the four tiny items
    # get grouped together (each ~2 words) rather than each becoming its
    # own near-empty chunk.
    assert citations[-1] == "N.J.A.C. 5:23-2.3(a).1+"
    assert len(chunks) == 2
    assert "short one" in chunks[-1]["text"]
    assert "short four" in chunks[-1]["text"]


def test_njac_chunk_indexes_history_as_a_separate_chunk():
    # Regression test: the History block used to be discarded entirely (see
    # docs/AllDevFlow.md's eval-set finding -- "when was this amended"
    # questions had a real, un-indexed answer in the source PDF).
    text = (
        "N.J.A.C. 5:23-12.5\n\n"
        "§ 5:23-12.5 Registration fee\n"
        "The initial registration fee shall be $76.00.\n"
        "History\n"
        "HISTORY:\n"
        "Amended by R.2014 d.149, effective October 6, 2014.\n"
        "See: 46 N.J.R. 898(a), 46 N.J.R. 2024(a).\n"
        "Updated the fee amounts.\n"
        "Annotations\n"
        "Notes\n"
        "Chapter Notes\n"
        "NEW JERSEY ADMINISTRATIVE CODE\n"
        "Copyright (c) 2026 by the New Jersey Office of Administrative Law\n"
        "End of Document"
    )

    chunks = njac_chunk("doc1", text)

    citations = [c["citation"] for c in chunks]
    assert "N.J.A.C. 5:23-12.5" in citations
    assert "N.J.A.C. 5:23-12.5 History" in citations

    operative = next(c for c in chunks if c["citation"] == "N.J.A.C. 5:23-12.5")
    assert operative["chunk_type"] == "njac_section"
    assert "Annotations" not in operative["text"]
    assert "2014" not in operative["text"]

    history = next(c for c in chunks if c["citation"] == "N.J.A.C. 5:23-12.5 History")
    assert history["chunk_type"] == "njac_history"
    assert "October 6, 2014" in history["text"]
    assert "Updated the fee amounts" in history["text"]
    assert "Annotations" not in history["text"]
    assert "Copyright" not in history["text"]


def test_njac_chunk_strips_annotations_footer_when_no_history_block():
    # Regression test: found live in the real corpus (22 chunks, e.g.
    # N.J.A.C. 5:23-1.2) -- a section with no History block still had the
    # trailing Annotations/Notes/Chapter Notes/Copyright boilerplate leak
    # straight into its indexed, retrievable operative text.
    text = (
        "N.J.A.C. 5:23-1.2\n\n"
        "§ 5:23-1.2 Purpose\n"
        "This subchapter is adopted pursuant to the Uniform Construction Code Act.\n"
        "Annotations\n"
        "Notes\n"
        "Chapter Notes\n"
        "NEW JERSEY ADMINISTRATIVE CODE\n"
        "Copyright (c) 2026 by the New Jersey Office of Administrative Law\n"
        "End of Document"
    )

    chunks = njac_chunk("doc1", text)

    assert len(chunks) == 1
    assert "Annotations" not in chunks[0]["text"]
    assert "Copyright" not in chunks[0]["text"]
    assert "Uniform Construction Code Act" in chunks[0]["text"]


def test_njac_chunk_splits_oversized_history_into_multiple_chunks():
    entry = (
        "Amended by R.2000 d.100, effective January 1, 2000. "
        "See: 30 N.J.R. 100(a), 30 N.J.R. 200(b). "
        "Some amendment description text here to pad the word count out nicely. "
    )
    text = (
        "N.J.A.C. 5:23-4.20\n\n"
        "§ 5:23-4.20 Big Section\n"
        "Operative text here.\n"
        "History\n"
        "HISTORY:\n"
        f"{entry * 20}\n"
        "Annotations\n"
        "Notes\n"
        "Chapter Notes\n"
        "NEW JERSEY ADMINISTRATIVE CODE\n"
        "Copyright (c) 2026\n"
        "End of Document"
    )

    chunks = njac_chunk("doc1", text)

    history_chunks = [c for c in chunks if c["chunk_type"] == "njac_history"]
    assert len(history_chunks) > 1
    assert all(c["word_count"] <= 500 for c in history_chunks)
    assert [c["citation"] for c in history_chunks] == [
        f"N.J.A.C. 5:23-4.20 History ({i + 1})" for i in range(len(history_chunks))
    ]


def test_dedupe_chunk_ids_disambiguates_collisions():
    chunks = [
        {"chunk_id": "doc1__5:23-1(a).1+"},
        {"chunk_id": "doc1__5:23-1(a).1+"},
        {"chunk_id": "doc1__5:23-1(b)"},
    ]

    deduped = _dedupe_chunk_ids(chunks)

    assert [c["chunk_id"] for c in deduped] == [
        "doc1__5:23-1(a).1+",
        "doc1__5:23-1(a).1+#2",
        "doc1__5:23-1(b)",
    ]


# ---------------------------------------------------------------------------
# generic.py
# ---------------------------------------------------------------------------


def test_split_sentences_empty_text_returns_no_sentences():
    assert split_sentences("   \n\n  ") == []


def test_split_sentences_splits_on_sentence_boundaries():
    text = "Doors shall be 36 inches wide. Ramps shall not exceed 1:12 slope."

    sentences = split_sentences(text)

    assert sentences == [
        "Doors shall be 36 inches wide.",
        "Ramps shall not exceed 1:12 slope.",
    ]


def test_chunk_page_produces_generic_chunk_with_no_citation():
    chunks, next_index = chunk_page("doc1", 3, "Handrails shall be continuous. They shall not rotate.", 0)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk["chunk_id"] == "doc1_0"
    assert chunk["chunk_type"] == "generic"
    assert chunk["citation"] is None
    assert chunk["page_number"] == 3
    assert chunk["word_count"] == len(chunk["text"].split())
    assert next_index == 1


def test_generic_chunk_numbers_pages_and_continues_chunk_index_across_pages():
    pages = ["First page sentence one. First page sentence two.", "Second page sentence one."]

    chunks = generic_chunk("doc1", pages)

    assert [c["page_number"] for c in chunks] == [1, 2]
    # chunk_id index threads through generic_chunk() across pages rather than
    # restarting at 0 for each page.
    assert [c["chunk_id"] for c in chunks] == ["doc1_0", "doc1_1"]


def test_generic_chunk_skips_empty_pages():
    pages = ["Real content sentence here.", "", "   "]

    chunks = generic_chunk("doc1", pages)

    assert len(chunks) == 1
    assert chunks[0]["page_number"] == 1
