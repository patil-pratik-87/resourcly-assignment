from resourcly.models import Issue


class NotFound(LookupError):
    pass


class UnreadableDrawing(ValueError):
    pass


class EmptyRequest(ValueError):
    """A chat message with neither text nor a file."""


class UploadTooLarge(ValueError):
    """A message with a file over the size cap, or with more files than the cap allows."""


class UnsupportedUpload(ValueError):
    """An uploaded file the agent cannot take: not a PDF or an image, or unreadable."""


class InvalidDocument(ValueError):
    def __init__(self, issues: list[Issue]):
        self.issues = issues
        super().__init__(f"{len(issues)} validation issue(s)")


class InvalidVersion(ValueError):
    pass
