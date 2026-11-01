import re
import threading
from pathlib import Path, PurePath

import pymupdf

from resourcly.errors import NotFound, UnsupportedUpload
from resourcly.models import StoredFile

# Leading bytes of each file type the agent takes, its media type and its file extension.
SIGNATURES = (
    (b"%PDF", "application/pdf", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"II*\x00", "image/tiff", "tiff"),
    (b"MM\x00*", "image/tiff", "tiff"),
)
EXTENSIONS = {extension: media for _, media, extension in SIGNATURES}
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class FileUploadStoreAdapter:
    """Uploaded files, in one folder per request: `<root>/<request id>/files/`.

    Each file is kept as sent, under an item id made from its name. An image is also stored as a
    one-page PDF, so every item has `<item id>.pdf` for the readers. The
    type is told from the file's first bytes, never from its name.
    """

    def __init__(self, root: Path):
        self.root = root
        self._lock = threading.Lock()

    def save_file(self, request_id: str, name: str, content: bytes) -> StoredFile:
        media, extension = _sniff(name, content)
        pdf = content if extension == "pdf" else _image_pdf(name, content, extension)
        pages = _page_count(name, pdf)
        folder = self.folder(request_id)
        with self._lock:
            folder.mkdir(parents=True, exist_ok=True)
            item_id = _unique(folder, _item_id(name))
            (folder / f"{item_id}.pdf").write_bytes(pdf)
            if extension != "pdf":
                (folder / f"{item_id}.{extension}").write_bytes(content)
        return StoredFile(
            item_id=item_id,
            name=PurePath(name).name,
            media_type=media,
            size=len(content),
            pages=pages,
        )

    def folder(self, request_id: str) -> Path:
        return self.root / _safe(request_id) / "files"

    def path(self, request_id: str, item_id: str) -> Path:
        folder = self.folder(request_id)
        _safe(item_id)
        for extension in EXTENSIONS:
            path = folder / f"{item_id}.{extension}"
            if extension != "pdf" and path.is_file():
                return path
        path = folder / f"{item_id}.pdf"
        if not path.is_file():
            raise NotFound(f"request {request_id} has no file {item_id}")
        return path

    def original(self, request_id: str, item_id: str) -> tuple[bytes, str]:
        path = self.path(request_id, item_id)
        return path.read_bytes(), EXTENSIONS[path.suffix[1:]]


def _sniff(name: str, content: bytes) -> tuple[str, str]:
    for signature, media, extension in SIGNATURES:
        if content.startswith(signature):
            return media, extension
    raise UnsupportedUpload(f"{PurePath(name).name} is not a PDF, PNG, JPEG or TIFF file")


def _image_pdf(name: str, content: bytes, extension: str) -> bytes:
    try:
        with pymupdf.open(stream=content, filetype=extension) as image:
            return image.convert_to_pdf()
    except (pymupdf.FileDataError, RuntimeError, ValueError) as error:
        raise UnsupportedUpload(f"{PurePath(name).name} is not a readable image") from error


def _page_count(name: str, pdf: bytes) -> int:
    try:
        with pymupdf.open(stream=pdf, filetype="pdf") as document:
            if document.page_count < 1:
                raise UnsupportedUpload(f"{PurePath(name).name} has no pages")
            return document.page_count
    except (pymupdf.FileDataError, RuntimeError) as error:
        raise UnsupportedUpload(f"{PurePath(name).name} is not a readable PDF") from error


def _item_id(name: str) -> str:
    """The file's name without its folder and extension, as letters, digits, `_`, `.` and `-`."""
    stem = PurePath(name.replace("\\", "/")).stem
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem)
    return re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "", cleaned) or "file"


def _unique(folder: Path, item_id: str) -> str:
    found, number = item_id, 1
    while (folder / f"{found}.pdf").exists():
        number += 1
        found = f"{item_id}-{number}"
    return found


def _safe(name: str) -> str:
    if not SAFE_NAME.match(name) or ".." in name:
        raise NotFound(f"'{name}' is not a request or file name")
    return name
