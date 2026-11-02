import json
import math
from dataclasses import dataclass
from pathlib import Path

from resourcly.errors import InvalidVersion
from resourcly.models import Attachment, LayerVerdict, Route
from resourcly.ports import ImageEncoderPort

PROBE_FIELDS = ("encoder_model", "classes", "weights", "bias")


@dataclass(frozen=True)
class LinearProbe:
    """A multinomial logistic regression over an image embedding: the probability of each route.

    It knows drawing, photo and other, the files that fit no case, so a page of text or a logo
    pulls the drawing and photo probabilities down instead of being forced into one of them. Only
    the regression is trained, by scripts/train_route_probe.py, and its file records the encoder
    whose embeddings it was trained on.
    """

    encoder_model: str
    classes: tuple[str, ...]
    weights: tuple[tuple[float, ...], ...]  # one row per class
    bias: tuple[float, ...]

    @classmethod
    def load(cls, path: Path) -> "LinearProbe":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise InvalidVersion(f"{path.name} cannot be read as a probe: {error}") from error
        missing = [name for name in PROBE_FIELDS if name not in data]
        if missing:
            raise InvalidVersion(f"{path.name} is not a probe: it lacks {', '.join(missing)}")
        routes = {route.value for route in Route}
        for name in data["classes"]:
            if name not in routes:
                raise InvalidVersion(f"{path.name} names {name}, which is not a route")
        classes, weights, bias = data["classes"], data["weights"], data["bias"]
        if not len(classes) == len(weights) == len(bias):
            raise InvalidVersion(
                f"{path.name} has {len(classes)} classes, {len(weights)} weight rows"
                f" and {len(bias)} biases"
            )
        return cls(
            data["encoder_model"],
            tuple(classes),
            tuple(tuple(row) for row in weights),
            tuple(bias),
        )

    @property
    def size(self) -> int:
        return len(self.weights[0])

    def probabilities(self, vector: list[float]) -> dict[str, float]:
        scores = [
            b + sum(w * x for w, x in zip(row, vector, strict=True))
            for row, b in zip(self.weights, self.bias, strict=True)
        ]
        top = max(scores)  # subtracted so exp() cannot overflow on a sure score
        exps = [math.exp(score - top) for score in scores]
        return {name: e / sum(exps) for name, e in zip(self.classes, exps, strict=True)}


class ProbeRouteAdapter:
    """Layer 2 of the router: a linear probe on a frozen image embedding.

    It decides the route it gives the highest probability when that is at least `threshold`, and
    otherwise passes the request on with its guess.
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
        if len(vector) != self.probe.size:
            raise ValueError(
                f"the embedding has {len(vector)} numbers, the probe takes {self.probe.size}"
            )
        probabilities = self.probe.probabilities(vector)
        name = max(probabilities, key=probabilities.__getitem__)
        confidence = probabilities[name]
        reason = f"the probe gives {name} {confidence:.3f}"
        if confidence >= self.threshold:
            return LayerVerdict(Route(name), reason, confidence, probabilities)
        return LayerVerdict(None, f"{reason}, below {self.threshold}", confidence, probabilities)
