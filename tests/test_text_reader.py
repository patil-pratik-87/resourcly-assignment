import pymupdf

from resourcly.adapters.text_reader import PyMuPDFTextReaderAdapter, callout_lines
from resourcly.bootstrap import PROJECT_ROOT
from tests.conftest import CTC01

DRAWINGS = PROJECT_ROOT / "data" / "drawings"


def test_reads_the_title_block_entries_as_records() -> None:
    document = PyMuPDFTextReaderAdapter(DRAWINGS).read(CTC01).document

    assert document["drawing"] == CTC01
    assert document["page_count"] == 1
    assert sorted((v["page"], v["callout"], v["raw"]) for v in document["values"]) == [
        (1, "title_block", "Includes Atomic Test Cases - 1, 2, 3, 4, 7, 8, 17, 21, 33, 48"),
        (1, "title_block", "NIST PMI Test Models - 2012"),
        (1, "title_block", "PMI Complex Test Case 1"),
        (1, "title_block", "Rev D"),
        (1, "title_block", "Test Model 1"),
        (1, "title_block", "nist_ctc_01_asme1_rd"),
    ]


def test_reads_numbered_and_free_notes_as_one_record_each() -> None:
    reader = PyMuPDFTextReaderAdapter(DRAWINGS)

    ftc06 = reader.read("nist_ftc_06_asme1_rd").document["values"]
    ctc03 = reader.read("nist_ctc_03_asme1_rc").document["values"]

    notes = [v["raw"] for v in ftc06 if v["callout"] == "note"]
    assert notes[0] == (
        "1. CAD MODEL ___________ REV. __ IS REQUIRED TO COMPLETE PRODUCT DEFINITION."
    )
    assert notes[-1] == "5. UNITS: INCHES"
    assert len(notes) == 5
    assert all(v["kind"] == v["callout"] for v in ftc06)
    assert [v["raw"] for v in ctc03 if v["callout"] == "note"] == [
        "Datum Feature F not referenced - justifies placing MCS at center of large hole on flange"
    ]


def test_leaves_callouts_in_the_text_layer_alone() -> None:
    values = PyMuPDFTextReaderAdapter(DRAWINGS).read("nist_ftc_07_asme1_rd").document["values"]

    assert not [v["raw"] for v in values if "Ø" in v["raw"] or "+.00" in v["raw"]]


def test_skips_note_headings_also_in_the_sheet_border() -> None:
    values = PyMuPDFTextReaderAdapter(DRAWINGS).read("nist_ftc_07_asme1_rd").document["values"]

    assert "NOTES (UNLESS OTHERWISE SPECIFIED):" not in [v["raw"] for v in values]


def test_lists_the_short_text_it_skips_as_callout_lines() -> None:
    with pymupdf.open(DRAWINGS / "nist_ftc_07_asme1_rd.pdf") as pdf:
        lines = [text for text, _ in callout_lines(pdf[1])]
    with pymupdf.open(DRAWINGS / f"{CTC01}.pdf") as pdf:
        ctc01 = callout_lines(pdf[0])

    assert "2X Ø.594 +.012" in lines
    assert "3X Ø.875 ±.020" in lines
    assert "Rev D" not in lines
    assert ctc01 == []
