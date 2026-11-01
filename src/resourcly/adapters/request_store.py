import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from resourcly.errors import NotFound
from resourcly.models import RequestRecord

SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class JsonRequestStoreAdapter:
    """Chat requests as JSON beside their files: `<root>/<request id>/request.json`.

    Each drawing's document is `<root>/<request id>/results/<item id>.json`. A file is written to a
    temporary name and renamed into place, so a reader never sees half a file.
    """

    def __init__(self, root: Path):
        self.root = root
        self._lock = threading.Lock()

    def save(self, record: RequestRecord) -> None:
        self._write(
            self._folder(record.request_id) / "request.json", record.model_dump(mode="json")
        )

    def load(self, request_id: str) -> RequestRecord:
        path = self._folder(request_id) / "request.json"
        if not path.is_file():
            raise NotFound(f"no request '{request_id}'")
        return RequestRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self, limit: int) -> list[RequestRecord]:
        records = [
            RequestRecord.model_validate_json(path.read_text(encoding="utf-8"))
            for path in self.root.glob("*/request.json")
        ]
        records.sort(key=lambda record: record.created_at, reverse=True)
        return records[:limit]

    def save_result(self, request_id: str, item_id: str, document: dict[str, Any]) -> None:
        self._write(self._folder(request_id) / "results" / f"{_safe(item_id)}.json", document)

    def load_result(self, request_id: str, item_id: str) -> dict[str, Any]:
        path = self._folder(request_id) / "results" / f"{_safe(item_id)}.json"
        if not path.is_file():
            raise NotFound(f"request {request_id} has no result for {item_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _folder(self, request_id: str) -> Path:
        return self.root / _safe(request_id)

    def _write(self, path: Path, data: Any) -> None:
        text = json.dumps(data, ensure_ascii=False, indent=2)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(text, encoding="utf-8")
            os.replace(temporary, path)


def _safe(name: str) -> str:
    if not SAFE_NAME.match(name) or ".." in name:
        raise NotFound(f"'{name}' is not a request or file name")
    return name
