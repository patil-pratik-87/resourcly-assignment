"""Answer every photo of the hand check and store what came back, for a person to judge.

    uv run --extra router --extra vlm python scripts/check_photo_answers.py \\
        --out evals/photo-answers/runs/photo-v2.jsonl

Each case of evals/photo-answers/cases.jsonl, a photo under evals/gold/, goes to the photo answer
of the versions in use, as if the router had called it a photo. A row keeps the case, the
versions, the answer, the model's own text and the seconds it took. The verdicts are a person's,
in evals/photo-answers/verdicts/; nothing here scores the answers.
"""

import argparse
import json
import time
from pathlib import Path

from resourcly.bootstrap import PROJECT_ROOT, Services, Settings, open_services
from resourcly.models import Attachment, guess_media_type

CASES = PROJECT_ROOT / "evals" / "photo-answers" / "cases.jsonl"


def check(services: Services, cases: Path, gold: Path) -> list[dict]:
    rows = []
    for line in cases.read_text(encoding="utf-8").splitlines():
        case = json.loads(line)
        data = (gold / case["image"]).read_bytes()
        photo = Attachment(Path(case["image"]).name, guess_media_type(case["image"], data), data)
        request_id = f"photo-check:{case['case_id']}:{time.time_ns()}"
        began = time.perf_counter()
        answer = services.photo_answers.answer(photo, "", request_id)
        seconds = round(time.perf_counter() - began, 1)
        steps = {event.step: event for event in services.traces.lookup(request_id).events}
        rows.append(
            {
                **case,
                "failure": services.failure_name,
                "answer_version": services.answer_name,
                "answer": answer.model_dump(mode="json"),
                "model_text": steps["answer.photo"].output.get("text", ""),
                "seconds": seconds,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True, help="The JSONL file to write.")
    parser.add_argument("--cases", type=Path, default=CASES)
    args = parser.parse_args()
    settings = Settings.from_env()
    with open_services(settings) as services:
        rows = check(services, args.cases, settings.gold_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    print(f"wrote {args.out}: {len(rows)} answers, {sum(r['seconds'] for r in rows):.0f} s")


if __name__ == "__main__":
    main()
