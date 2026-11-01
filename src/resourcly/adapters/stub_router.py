import pymupdf

from resourcly.models import Attachment, LayerVerdict, Route


class StubRouteAdapter:
    """A model-free router layer with one structure rule per input, for tests and small machines.

    A PDF whose first page has at least `min_paths` vector paths is a drawing: the NIST drawings
    have 600 to 5,300, the NTSB reports fewer than 20. An image is a photo of a part, text alone is
    text, and anything else fits no case. It decides every request, so a router of this one layer
    never loads a model.
    """

    name = "stub"
    called = "stand-in structure rule, no model"

    def __init__(self, min_paths: int = 300):
        self.min_paths = min_paths

    def decide(self, attachment: Attachment | None) -> LayerVerdict:
        if attachment is None:
            return LayerVerdict(Route.TEXT, "A message without a file is text.", 1.0)
        if attachment.media_type.startswith("image/"):
            return LayerVerdict(Route.PHOTO, "An image is taken as a photo of a part.", 0.6)
        try:
            with pymupdf.open(stream=attachment.data, filetype="pdf") as pdf:
                paths = len(pdf[0].get_drawings())
        except (pymupdf.FileDataError, RuntimeError, ValueError):
            return LayerVerdict(Route.UNSUPPORTED, "Not a readable PDF.", 1.0)
        if paths >= self.min_paths:
            return LayerVerdict(
                Route.DRAWING,
                f"The first page has {paths} vector paths, at least {self.min_paths}:"
                " drawn like a technical drawing.",
                0.7,
            )
        return LayerVerdict(
            Route.UNSUPPORTED,
            f"The first page has {paths} vector paths, fewer than {self.min_paths}:"
            " a document of text or photos, not a drawing.",
            0.6,
        )
