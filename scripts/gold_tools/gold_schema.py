"""Write evals/gold/schema.json from the package models, which are the one source of the schema.

A test fails when the committed file is stale; run this after changing a model in models.py.

    uv run python scripts/gold_tools/gold_schema.py
"""

import json

from resourcly.bootstrap import PROJECT_ROOT
from resourcly.models import gold_json_schema

PATH = PROJECT_ROOT / "evals" / "gold" / "schema.json"


def render() -> str:
    return json.dumps(gold_json_schema(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    PATH.write_text(render(), encoding="utf-8")
    print(f"wrote {PATH}")
