import math
import os
import threading
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any, ClassVar

from resourcly.errors import ModelNotCached
from resourcly.models import Choice


def cached_snapshot(model_id: str, cache_dir: Path | None = None) -> Path:
    """The model's folder in the local Hugging Face cache, or the model id if it is a folder.

    Nothing is downloaded: a model that is not in the cache raises ModelNotCached.
    """
    if Path(model_id).is_dir():
        return Path(model_id)
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        return Path(snapshot_download(model_id, cache_dir=cache_dir, local_files_only=True))
    except LocalEntryNotFoundError as error:
        raise ModelNotCached(
            f"{model_id} is not in the local Hugging Face cache; download it once with"
            f" `hf download {model_id}` before reading drawings"
        ) from error


def option_probabilities(scores: list[float]) -> list[float]:
    """The options' first-token log probabilities, normalised to sum to 1 over the options."""
    top = max(scores)
    weights = [math.exp(score - top) for score in scores]
    return [weight / sum(weights) for weight in weights]


def option_mass(scores: list[float]) -> float:
    """The share of the first token's probability that the options hold together."""
    return sum(math.exp(score) for score in scores)


def _mlx_load(path: str) -> tuple[Any, Any]:
    import mlx.core as mx
    from mlx_vlm import load

    mx.clear_cache()
    return load(path)


class MlxVlmModelAdapter:
    """A vision-language model run locally through mlx-vlm on Apple silicon, such as Qwen3-VL.

    The weights load on the first call from the local Hugging Face cache, never from the network,
    and stay loaded for the next adapter of the same model, so an eval run pays the load once.
    One model is kept at a time. Decoding is greedy, so a call repeats. `choose` reads the
    probability of each option from the first answer token instead of generating text.
    """

    _loaded: ClassVar[dict[str, tuple[Any, Any]]] = {}
    _revisions: ClassVar[dict[str, str]] = {}
    # one model call at a time: API worker threads share the loaded weights and the GPU
    _lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(
        self,
        model_id: str,
        locate: Callable[[str], Path] = cached_snapshot,
        load: Callable[[str], tuple[Any, Any]] = _mlx_load,
    ):
        self.model_id = model_id
        self.locate = locate
        self.load = load

    def generate(self, prompt: str, images: list[bytes], max_tokens: int) -> str:
        with self._lock:
            model, processor = self._load()
            from mlx_vlm import generate
            from mlx_vlm.prompt_utils import apply_chat_template
            from PIL import Image

            formatted = apply_chat_template(processor, model.config, prompt, num_images=len(images))
            result = generate(
                model,
                processor,
                formatted,
                [Image.open(BytesIO(image)).convert("RGB") for image in images] or None,
                max_tokens=max_tokens,
                temperature=0.0,
                verbose=False,
            )
            return result.text

    @property
    def revision(self) -> str:
        """The snapshot folder the weights were loaded from, which is the commit in the cache."""
        return self._revisions.get(self.model_id, "not loaded")

    def choose(self, prompt: str, images: list[bytes], options: list[str]) -> Choice:
        with self._lock:
            model, processor = self._load()
            import mlx.core as mx
            from mlx_vlm import stream_generate
            from mlx_vlm.prompt_utils import apply_chat_template
            from PIL import Image

            formatted = apply_chat_template(processor, model.config, prompt, num_images=len(images))
            tokenizer = getattr(processor, "tokenizer", processor)
            ids = [tokenizer.encode(option, add_special_tokens=False)[0] for option in options]
            pictures = [Image.open(BytesIO(image)).convert("RGB") for image in images] or None
            for step in stream_generate(
                model, processor, formatted, pictures, max_tokens=1, temperature=0.0
            ):
                logprobs = step.logprobs.astype(mx.float32).reshape(-1)
                scores = [logprobs[i].item() for i in ids]
                probabilities = dict(zip(options, option_probabilities(scores), strict=True))
                return Choice(probabilities, option_mass(scores))
            raise RuntimeError(f"{self.model_id} gave no answer token")

    def _load(self) -> tuple[Any, Any]:
        with self._lock:
            if self.model_id not in self._loaded:
                # the weights are local; nothing may reach the network. huggingface_hub reads this
                # once, when it is first imported, which the cache lookup below may do
                os.environ["HF_HUB_OFFLINE"] = "1"
                path = self.locate(self.model_id)
                self._loaded.clear()
                self._loaded[self.model_id] = self.load(str(path))
                self._revisions[self.model_id] = Path(path).name
            return self._loaded[self.model_id]
