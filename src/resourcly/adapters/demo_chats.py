import json
import logging
import os
import shutil
from pathlib import Path

from resourcly.models import RequestRecord, TraceEvent
from resourcly.ports import TracePort

log = logging.getLogger(__name__)


def load_demo_chats(folder: Path, store: Path, trace: TracePort) -> list[str]:
    """Add each demo chat in `folder` that the request store at `store` does not have yet.

    A demo is `<folder>/<request id>/` in the stores' own layout: `request.json`, the `files/` and
    `results/` of its items, and `trace.json`, its trace events. demo/README.md says where each
    output comes from. A request already in the store is never replaced, whoever sent it, and the
    trace events are added only when the trace has none for the request. A demo that cannot be
    read is skipped with a warning. Returns the request ids added to the store.
    """
    added = []
    for source in sorted(folder.glob("*/request.json")):
        demo = source.parent
        try:
            record = RequestRecord.model_validate_json(source.read_text(encoding="utf-8"))
            events = [
                TraceEvent.model_validate(event)
                for event in json.loads((demo / "trace.json").read_text(encoding="utf-8"))
            ]
            if record.request_id != demo.name:
                raise ValueError(f"its request.json is request {record.request_id}")
        except (OSError, ValueError) as error:
            log.warning("skipping the demo chat in %s: %s", demo, error)
            continue
        target = store / demo.name
        if not (target / "request.json").exists():
            shutil.copytree(
                demo,
                target,
                ignore=shutil.ignore_patterns("request.json", "trace.json"),
                dirs_exist_ok=True,
            )
            # the record last, so the store lists the request only once its files are in place
            temporary = target / "request.json.tmp"
            marked = record.model_copy(update={"demo": True})
            temporary.write_text(marked.model_dump_json(indent=2), encoding="utf-8")
            os.replace(temporary, target / "request.json")
            added.append(demo.name)
        if not trace.find(demo.name):
            for event in events:
                trace.record(event)
    return added
