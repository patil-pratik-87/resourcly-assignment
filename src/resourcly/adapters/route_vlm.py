from resourcly.adapters.route_pictures import png
from resourcly.models import Attachment, LayerVerdict, Route
from resourcly.ports import VisionModelPort

# The prompt of a version defines these letters in this order.
OPTIONS = {"A": Route.DRAWING, "B": Route.PHOTO, "C": Route.OTHER}


class VlmRouteAdapter:
    """Layer 3 of the router: a local vision-language model asked one multiple-choice question.

    The model sees the picture (page 1 of a PDF, or the image, at most `max_side` pixels on its
    long side) and never the user's text. It always decides: A is a drawing, B a photo of a part,
    and C something else, a file that fits no case.
    """

    name = "vlm"

    def __init__(self, model: VisionModelPort, prompt: str, max_side: int = 768):
        self.model = model
        self.prompt = prompt
        self.max_side = max_side

    @property
    def called(self) -> str:
        return (
            f"{self.model.model_id} (snapshot {self.model.revision}), one multiple-choice question"
        )

    def decide(self, attachment: Attachment | None) -> LayerVerdict:
        if attachment is None:
            return LayerVerdict(None, "no attachment for the model")
        choice = self.model.choose(self.prompt, [png(attachment, self.max_side)], list(OPTIONS))
        answer = choice.probabilities
        letter = max(answer, key=answer.__getitem__)
        route = OPTIONS[letter]
        probabilities = {OPTIONS[option].value: p for option, p in answer.items()}
        reason = (
            f"{self.model.model_id} answers {letter} ({route.value}) at {answer[letter]:.3f};"
            f" the letters hold {choice.mass:.3f} of the first token"
        )
        return LayerVerdict(route, reason, answer[letter], probabilities)
