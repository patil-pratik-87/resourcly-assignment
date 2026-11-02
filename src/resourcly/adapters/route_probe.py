import json
import math
from dataclasses import dataclass
from pathlib import Path

from resourcly.errors import InvalidVersion
from resourcly.models import Attachment, LayerVerdict, Route
from resourcly.ports import ImageEncoderPort

PROBE_FIELDS = ("encoder_model", "weights", "bias")


@dataclass(frozen=True)
class LinearProbe:
    """A logistic regression over an image embedding: the probability that a picture is a drawing.

    Only the regression is trained, by scripts/train_route_probe.py, and its file records the
    encoder whose embeddings it was trained on.
    """

    encoder_model: str
    weights: tuple[float, ...]
    bias: float

    @classmethod
    def load(cls, path: Path) -> "LinearProbe":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise InvalidVersion(f"{path.name} cannot be read as a probe: {error}") from error
        missing = [name for name in PROBE_FIELDS if name not in data]
        if missing:
            raise InvalidVersion(f"{path.name} is not a probe: it lacks {', '.join(missing)}")
        return cls(data["encoder_model"], tuple(data["weights"]), data["bias"])

    def p_drawing(self, vector: list[float]) -> float:
        score = self.bias + sum(w * x for w, x in zip(self.weights, vector, strict=True))
        if score < 0:  # the two forms keep exp() from overflowing on a sure score
            return math.exp(score) / (1 + math.exp(score))
        return 1 / (1 + math.exp(-score))


class ProbeRouteAdapter:
    """Layer 2 of the router: a linear probe on a frozen image embedding.

    It decides drawing or photo when it is at least `threshold` sure, and otherwise passes the
    request on with its guess. It knows only those two cases, so a file that fits no case relies on
    the structure rules before it or the threshold.
    """

    name = "probe"

    def __init__(self, encoder: ImageEncoderPort, probe: LinearProbe, threshold: float):
        if probe.encoder_model != encoder.model_id:
            raise InvalidVersion(
                f"the probe was trained on {probe.encoder_model} embeddings, not {encoder.model_id}"
            )
        self.encoder = encoder
        self.probe = probe
        self.threshold = threshold

    @property
    def called(self) -> str:
        encoder = f"{self.encoder.model_id} (snapshot {self.encoder.revision})"
        return f"linear probe on {encoder}, deciding at {self.threshold}"

    def decide(self, attachment: Attachment | None) -> LayerVerdict:
        if attachment is None:
            return LayerVerdict(None, "no attachment for the probe")
        vector = self.encoder.encode(attachment)
        if len(vector) != len(self.probe.weights):
            raise ValueError(
                f"the embedding has {len(vector)} numbers, the probe takes"
                f" {len(self.probe.weights)}"
            )
        p = self.probe.p_drawing(vector)
        route, confidence = (Route.DRAWING, p) if p >= 0.5 else (Route.PHOTO, 1 - p)
        probabilities = {Route.DRAWING.value: p, Route.PHOTO.value: 1 - p}
        reason = f"the probe gives {route.value} {confidence:.3f}"
        if confidence >= self.threshold:
            return LayerVerdict(route, reason, confidence, probabilities)
        return LayerVerdict(None, f"{reason}, below {self.threshold}", confidence, probabilities)
