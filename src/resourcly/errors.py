from resourcly.models import Issue


class NotFound(LookupError):
    pass


class UnreadableDrawing(ValueError):
    pass


class InvalidDocument(ValueError):
    def __init__(self, issues: list[Issue]):
        self.issues = issues
        super().__init__(f"{len(issues)} validation issue(s)")
