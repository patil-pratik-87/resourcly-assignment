"""Write outputs/<drawing>.json from the latest full run of a reader version on all gold.

    uv run evals run reader --version vector-crop-v1 --split all
    uv run python scripts/write_outputs.py --version vector-crop-v1

Each file is the document the reader returned for that drawing, as the evals stored it. Only a run
of the version as it is now counts: a run made before the version file changed is skipped.
"""

import argparse
import json
import os
from pathlib import Path

from resourcly.bootstrap import PROJECT_ROOT, Settings, load_version
from resourcly.eval_harness.cli import DEFAULT_STORE
from resourcly.eval_harness.store import SqliteResultStore


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--version", default="vector-crop-v1", help="A reader version.")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "outputs")
    parser.add_argument(
        "--store", type=Path, default=Path(os.environ.get("RESOURCLY_EVALS_DB", DEFAULT_STORE))
    )
    args = parser.parse_args(argv)
    current = load_version(Settings.from_env(), "reader", args.version).hash
    with SqliteResultStore.open(args.store) as store:
        runs = [
            run
            for run in store.runs("reader", args.version)
            if run.version_hash == current
            and run.split == "all"
            and not run.case_ids
            and run.finished_at
        ]
        if not runs:
            raise SystemExit(
                f"no finished run of {args.version} on all gold; make one with"
                f" `uv run evals run reader --version {args.version} --split all`"
            )
        run = max(runs, key=lambda run: run.started_at)
        cases = store.cases(run.run_id)
    args.out.mkdir(parents=True, exist_ok=True)
    written = 0
    for case in cases:
        document = (case.prediction or {}).get("document")
        if document:
            path = args.out / f"{case.case_id}.json"
            path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
            written += 1
    print(f"wrote {written} file(s) to {args.out} from run {run.run_id}")


if __name__ == "__main__":
    main()
