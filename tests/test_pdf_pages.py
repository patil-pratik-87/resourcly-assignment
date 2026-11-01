import os
import shutil
from pathlib import Path

import pytest

from resourcly.adapters.pdf_pages import PyMuPDFPageAdapter
from resourcly.bootstrap import PROJECT_ROOT
from resourcly.errors import NotFound, UnreadableDrawing
from tests.conftest import CTC01

DRAWINGS = PROJECT_ROOT / "data" / "drawings"


def test_corrupt_pdf_is_an_application_error(tmp_path: Path) -> None:
    (tmp_path / "broken.pdf").write_bytes(b"%PDF-1.4 not really")
    pages = PyMuPDFPageAdapter(tmp_path)

    with pytest.raises(UnreadableDrawing, match="broken.pdf is not a readable PDF"):
        pages.page_count("broken")
    with pytest.raises(NotFound):
        pages.page_count("absent")


def test_documents_stay_open_until_close_and_reopen_on_change(tmp_path: Path) -> None:
    path = tmp_path / f"{CTC01}.pdf"
    shutil.copy(DRAWINGS / f"{CTC01}.pdf", path)
    pages = PyMuPDFPageAdapter(tmp_path)
    assert pages.page_count(CTC01) == 1
    first = pages._open[CTC01][1]

    shutil.copy(DRAWINGS / "nist_ftc_06_asme1_rd.pdf", path)
    os.utime(path, (1, 1))
    assert pages.page_count(CTC01) == 3
    assert first.is_closed

    pages.close()
    assert pages._open == {}
