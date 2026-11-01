import re
from typing import Any

from resourcly.errors import InvalidDocument, NotFound
from resourcly.models import (
    DrawingSummary,
    GoldDocument,
    Issue,
    TitleBlock,
    undefined_datums,
    validate_document,
)
from resourcly.ports import (
    DrawingPagePort,
    GoldStorePort,
    Source,
    Splits,
)

DRAWING_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class GoldService:
    def __init__(self, store: GoldStorePort, pages: DrawingPagePort):
        self.store = store
        self.pages = pages

    def list_drawings(self) -> list[DrawingSummary]:
        gold = self.store.list_drawings()
        pdfs = set(self.pages.list_drawings())
        return [
            self._summary(name, gold.get(name), name in pdfs) for name in sorted(pdfs | gold.keys())
        ]

    def load(self, drawing: str) -> dict[str, Any]:
        _check_name(drawing)
        if self.store.exists(drawing):
            return self.store.load(drawing)
        return GoldDocument(
            drawing=drawing, page_count=self.pages.page_count(drawing), title_block=TitleBlock()
        ).model_dump(mode="json")

    def check(self, drawing: str, document: Any) -> list[Issue]:
        _check_name(drawing)
        _, issues = self._validate(drawing, document)
        return issues

    def save(self, drawing: str, document: Any) -> GoldDocument:
        _check_name(drawing)
        valid, issues = self._validate(drawing, document)
        if valid is None:
            raise InvalidDocument(issues)
        self.store.save(drawing, valid)
        return valid

    def check_all(self) -> dict[str, list[Issue]]:
        results = {}
        for drawing in self.store.list_drawings():
            try:
                results[drawing] = self.check(drawing, self.store.load(drawing))
            except InvalidDocument as error:
                results[drawing] = error.issues
        return results

    def splits(self) -> Splits:
        return self.store.load_splits()

    def render_page(self, drawing: str, page: int, dpi: int) -> bytes:
        _check_name(drawing)
        return self.pages.render(drawing, page, dpi)

    def _validate(self, drawing: str, document: Any) -> tuple[GoldDocument | None, list[Issue]]:
        valid, issues = validate_document(document)
        if valid is None:
            return None, issues
        if valid.drawing != drawing:
            issues.append(
                Issue(loc=["drawing"], message=f"must be '{drawing}', the file it is stored as")
            )
        if drawing in self.pages.list_drawings():
            pages = self.pages.page_count(drawing)
            if valid.page_count != pages:
                issues.append(Issue(loc=["page_count"], message=f"the PDF has {pages} page(s)"))
        # Partial gold lists a few values only, and a page-limited document covers only some
        # pages, so their frames may name datums defined elsewhere.
        partial = self.store.list_drawings().get(drawing) == "partial"
        if not partial and valid.page_coverage is None:
            issues.extend(undefined_datums(valid))
        return (None, issues) if issues else (valid, [])

    def _summary(self, drawing: str, source: Source | None, has_pdf: bool) -> DrawingSummary:
        values = approved = issues = 0
        page_count = self.pages.page_count(drawing) if has_pdf else 0
        if source is not None:
            try:
                document = self.store.load(drawing)
                found = self.check(drawing, document)
                rows = document.get("values", []) if isinstance(document, dict) else []
                values = len(rows)
                approved = sum(
                    1 for row in rows if isinstance(row, dict) and row.get("status") == "approved"
                )
                issues = len(found)
            except InvalidDocument as error:
                issues = len(error.issues)
        return DrawingSummary(
            drawing=drawing,
            page_count=page_count,
            has_gold=source is not None,
            source=source,
            values=values,
            approved=approved,
            issues=issues,
        )


def _check_name(drawing: str) -> None:
    if not DRAWING_NAME.match(drawing):
        raise NotFound(f"'{drawing}' is not a drawing name")
