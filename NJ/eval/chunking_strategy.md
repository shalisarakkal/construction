# Chunking Strategy — sketched against njac_5_23_12.pdf (Elevator Safety Subcode)

## Why not the original plan (sentence-based, 200-500 words)

Reading the actual file changed the design. NJAC regulation PDFs are not prose documents —
they're already hierarchically structured (section > lettered subsection > numbered item >
romanette), every section is clearly delimited by a `§ 5:23-12.X <Title>` heading, and they
contain real tables (fee schedules in §12.6) that a sentence-splitter would flatten into
unreadable text. Structure-aware chunking will beat generic word-count chunking here, both
in retrieval accuracy and in citation quality.

## 1. Extraction

- Use `pdfplumber` page-by-page text extraction (the text layer is clean and native — no OCR
  needed for these NJ-hosted regulation PDFs).
- Use `pdfplumber`'s `extract_tables()` on pages containing fee schedules (detected by keyword
  match: "fee", "$", or a page with >3 rows of mostly-numeric cells) and keep them as separate
  table objects rather than flattening into paragraph text.

## 2. Boilerplate stripping (before chunking, not during)

Every section repeats a fixed skeleton:

```
N.J.A.C. 5:23-12.X
This file includes all Regulations adopted and published through the New Jersey Register, Vol. ...
NJ - New Jersey Administrative Code > TITLE 5 ... > SUBCHAPTER 12. ELEVATOR SAFETY SUBCODE
§ 5:23-12.X <Title>
<BODY>
History
HISTORY:
<amendment log>
Annotations
Notes
 Chapter Notes
NEW JERSEY ADMINISTRATIVE CODE
Copyright © 2026 by the New Jersey Office of Administrative Law
End of Document
```

Regex-detect and strip everything from `History` / `HISTORY:` to `End of Document` into a
separate `amendment_history` field (stored, not embedded). This is regulatory provenance, not
operative law — including it in retrieval chunks would dilute embeddings with dates and R.20XX
citation noise that rarely answers a user's actual question. Keep it queryable as metadata for
questions like "when was this last amended."

The repeated breadcrumb (`NJ - New Jersey Administrative Code > TITLE 5...`) is also stripped
into structured metadata (`title`, `chapter`, `subchapter`) rather than kept in the chunk body.

## 3. Primary chunk boundary = the regulatory section

Each `§ 5:23-12.X` is the top-level chunk unit — not a word count. Sections here range from
~150 words (§12.7 Licensing, §12.5 Registration fee) to ~1,200 words (§12.8 Alterations, §12.6
Fees). This variance is fine; regulatory sections are the unit a person actually cites and reads
as one thought.

## 4. Recursive split only when a section is too large

If a section's body exceeds ~500 words (roughly §12.3, §12.4, §12.6, §12.8, §12.9 in this
sample), split recursively along the document's own structure, in this order of preference:

1. Split on lettered subsections `(a)`, `(b)`, `(c)` — never mid-subsection.
2. If a lettered subsection is itself too large (e.g. §12.8(b) has 33 numbered "minor work"
   items), split on the numbered items `1.`, `2.`, `3.` — grouping consecutive short items
   together up to ~400 words rather than one item per chunk (a single "Addition of rope
   equalizers" line is too small and context-free to embed alone).
3. Only fall back to sentence-level splitting inside a single numbered item if that item alone
   exceeds ~400 words (rare in this sample, but possible in denser subchapters like the building
   subcode).

No arbitrary sliding-window overlap between chunks. Regulatory text is referential/structural,
not narrative — instead of overlap, every chunk is prefixed with a synthetic header line (see
below) that restores context regardless of where the split happened.

## 5. Header stuffing (context injection instead of overlap)

Every chunk — even a child chunk from a long section — gets a synthetic first line:

```
N.J.A.C. 5:23-12.6(b)(2)(vi) — Test and inspection fees — one-year periodic inspection,
manlifts/stairway chairlifts/wheelchair lifts
```

This means a chunk retrieved in total isolation (top-1 hit, no neighbors) still tells the LLM
exactly what it's looking at and how to cite it — directly serving the citation requirement in
the original plan (`(doc, page)` → here, `(doc, section)` is the more meaningful citation unit
for regulations; page number is incidental to how NJ paginated the PDF export, section number is
what a construction official actually cites).

## 6. Cross-reference extraction (metadata, not inline expansion)

Regex-scan each chunk for citation patterns and store them as a `references` array on the chunk:

- `N.J.A.C. 5:23-\d+(-\d+)?(\.\d+)?` (internal NJAC cross-refs, e.g. "N.J.A.C. 5:23-2.32")
- `ASME A17\.\d|ASME A18\.\d|ASME A90\.\d` (referenced private standards — not retrievable
  content per our earlier copyright decision, but useful to surface as "see also X, not
  available in this system")
- `ICC A117\.1` (accessibility standard cross-ref)

This doesn't change retrieval at query time yet, but sets up two Phase-2/3 wins cheaply:
(a) when a chunk cites another NJAC section, that section can be auto-included in the context
    block even if it didn't independently score high on similarity ("graph-assisted retrieval"),
(b) when an answer only exists inside a referenced private-standard document we don't have
    (ASME/ICC), the system can say "this may also depend on ASME A17.1, which is not indexed
    here" instead of silently guessing.

## 7. Table handling (§12.6 fee schedules)

Tables become their own chunk type (`chunk_type: "table"`), stored as markdown tables (row =
device type or fee category, columns = fee amount / conditions), with the same header-stuffing
convention (`N.J.A.C. 5:23-12.6(a)(1) — basic acceptance test fees`). This lets a question like
"what's the fee for a hydraulic elevator acceptance test" retrieve one small, precise table chunk
rather than a paragraph containing seven unrelated dollar amounts.

## 8. Final chunk metadata schema

```json
{
  "chunk_id": "njac_5_23_12__12.6_b_2_vi",
  "doc_id": "njac_5_23_12",
  "citation": "N.J.A.C. 5:23-12.6(b)(2)(vi)",
  "section_title": "Test and inspection fees",
  "chunk_type": "body | table",
  "text": "...",
  "word_count": 187,
  "references": ["N.J.A.C. 5:23-12.2", "ASME A17.1"],
  "amendment_history_ref": "njac_5_23_12__12.6__history"
}
```

## What this does NOT solve yet (flagged, not fixed here)

- Effective-dating: some fee/requirement values have changed over amendment history (e.g.
  registration fee went $54 → $68 → $76 across rewrites). The chunk as extracted reflects only
  the *current* text (correct for "what is the current fee" queries), but a query like "what was
  the fee in 2010" would need the amendment log parsed into a timeline — out of scope for the
  sketch, worth a backlog note.
- This sample document has no real CAD/GIS/image content, so OCR-path chunking is still
  untested — worth doing a second small sketch against an OCR'd source once one is available.
