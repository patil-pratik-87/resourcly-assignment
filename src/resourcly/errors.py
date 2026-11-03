from resourcly.models import Issue


class NotFound(LookupError):
    pass


class UnreadableDrawing(ValueError):
    pass


class EmptyRequest(ValueError):
    """A chat message with neither text nor a file."""


class UnknownTarget(ValueError):
    """A message about an earlier item or value that the request store does not hold."""


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


class ModelNotCached(LookupError):
    """A model the reader needs is not on this machine; readers never download one."""


class UnreadableAttachment(ValueError):
    """An attached file that opens but cannot be decoded or rendered into a picture."""
