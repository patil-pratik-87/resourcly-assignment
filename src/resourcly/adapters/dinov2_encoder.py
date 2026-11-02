import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from resourcly.adapters.mlx_vlm_model import cached_snapshot
from resourcly.adapters.route_pictures import picture
from resourcly.models import Attachment


def _torch_load(path: str) -> tuple[Any, Any, str]:
    import torch
    from transformers import AutoImageProcessor, AutoModel
    from transformers.utils import logging

    logging.disable_progress_bar()
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = AutoModel.from_pretrained(path).to(device).eval()
    return AutoImageProcessor.from_pretrained(path), model, device


class Dinov2EncoderAdapter:
    """A frozen DINOv2 image model run with PyTorch, on the Apple GPU when there is one.

    The embedding is the model's pooled output for the picture (page 1 of a PDF, or the image, at
    most `max_side` pixels on its long side), scaled to length 1. The weights load on the first
    call from the local Hugging Face cache, never from the network, and stay loaded for the next
    adapter of the same model.
    """

    _loaded: ClassVar[dict[str, tuple[Any, Any, str]]] = {}
    _revisions: ClassVar[dict[str, str]] = {}
    # one call at a time: API worker threads share the loaded weights and the GPU
    _lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(
        self,
        model_id: str,
        max_side: int = 1024,
        locate: Callable[[str], Path] = cached_snapshot,
        load: Callable[[str], tuple[Any, Any, str]] = _torch_load,
    ):
        self.model_id = model_id
        self.max_side = max_side
        self.locate = locate
        self.load = load

    @property
    def revision(self) -> str:
        """The snapshot folder the weights were loaded from, which is the commit in the cache."""
        return self._revisions.get(self.model_id, "not loaded")

    def encode(self, attachment: Attachment) -> list[float]:
        import torch

        seen = picture(attachment, self.max_side)
        with self._lock:
            processor, model, device = self._load()
            inputs = processor(images=seen, return_tensors="pt")
            with torch.no_grad():
                pooled = model(**{name: value.to(device) for name, value in inputs.items()})
            vector = torch.nn.functional.normalize(pooled.pooler_output.float(), dim=-1)
            return vector[0].cpu().tolist()

    def _load(self) -> tuple[Any, Any, str]:
        with self._lock:
            if self.model_id not in self._loaded:
                # the weights are local; nothing may reach the network. huggingface_hub reads this
                # once, when it is first imported, which the cache lookup below may do
                os.environ["HF_HUB_OFFLINE"] = "1"
                path = self.locate(self.model_id)
                self._loaded[self.model_id] = self.load(str(path))
                self._revisions[self.model_id] = Path(path).name
            return self._loaded[self.model_id]
