"""Checks that this machine can run the versions the app runs, each with the command that fixes it.

A failed check is a blocker when the app cannot run without it, such as a missing model, and a
warning when only part of it is missing, such as the chat screen for someone using the CLI.
"""

import os
import platform
import shutil
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib.util import find_spec

from resourcly.bootstrap import Settings, Version, load_version, model_cached, version_models
from resourcly.errors import InvalidVersion, NotFound

SYNC = "uv sync --extra vlm --extra router"
# The versions that run without Qwen3-VL, for a machine that cannot run it
NO_VLM = (
    "RESOURCLY_READER_VERSION=textlayer-v0 RESOURCLY_ROUTER_VERSION=stub-v0"
    " RESOURCLY_ANSWER_VERSION=captions-v0 uv run resourcly serve"
)
# The command that restores a file a version names, by the setting that names it.
FILE_FIXES = {"index": "make index", "probe": "git checkout -- versions/router/probes"}


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    fix: str = ""
    blocker: bool = True


@dataclass(frozen=True)
class System:
    """What the checks ask of the machine, so a test can stand in for it."""

    python: tuple[int, int]
    platform: str  # such as darwin-arm64
    which: Callable[[str], str | None]
    installed: Callable[[str], bool]
    cached: Callable[[str], bool]
    env: Mapping[str, str]

    @classmethod
    def current(cls) -> "System":
        return cls(
            python=(sys.version_info.major, sys.version_info.minor),
            platform=f"{sys.platform}-{platform.machine()}",
            which=shutil.which,
            installed=lambda module: find_spec(module) is not None,
            cached=model_cached,
            env=os.environ,
        )


def run(settings: Settings, system: System) -> list[Check]:
    """Every check, in the order a setup fixes them: tools, extras, models, versions, screen."""
    versions, version_checks = _versions(settings)
    models = [version_models(version) for version in versions]
    return [
        _python(system),
        _uv(system),
        _tool(system, "node", "brew install node", blocker=False),
        _mlx(system, needed=any("model" in named for named in models)),
        _torch(system, needed=any("encoder_model" in named for named in models)),
        *[_model(system, model_id) for model_id in needed_models(versions)],
        *version_checks,
        _chat(settings),
    ]


def needed_models(versions: list[Version]) -> list[str]:
    """The models the versions load, each once, in the order the versions name them."""
    return list(dict.fromkeys(m for v in versions for m in version_models(v).values()))


def running_versions(settings: Settings) -> list[Version]:
    """The versions the app runs that load; `run` reports the ones that do not."""
    return _versions(settings)[0]


def _versions(settings: Settings) -> tuple[list[Version], list[Check]]:
    versions, checks = [], []
    for component, name in settings.versions.items():
        try:
            version = load_version(settings, component, name)
        except (NotFound, InvalidVersion) as error:
            fix = next(
                (fix for key, fix in FILE_FIXES.items() if f"the {key} file" in str(error)),
                f"pick another with RESOURCLY_{component.upper()}_VERSION",
            )
            checks.append(Check(component, False, str(error), fix))
            continue
        versions.append(version)
        named = "".join(f", {key} {version.params[key]}" for key in version.files)
        checks.append(Check(component, True, f"{version.name} ({version.impl}){named}"))
    return versions, checks


def _python(system: System) -> Check:
    found = ".".join(map(str, system.python))
    if system.python == (3, 12):
        return Check("python", True, found)
    return Check("python", False, f"{found}, the project needs 3.12", "uv python install 3.12")


def _uv(system: System) -> Check:
    """uv on the PATH, or the one `uv run` names in UV when the PATH lacks it."""
    if system.which("uv") or "UV" not in system.env:
        return _tool(system, "uv", "curl -LsSf https://astral.sh/uv/install.sh | sh", True)
    folder = os.path.dirname(system.env["UV"])
    detail = f"{system.env['UV']} is not on PATH, so a shell cannot run uv"
    return Check("uv", False, detail, f'export PATH="{folder}:$PATH"', blocker=False)


def _tool(system: System, tool: str, fix: str, blocker: bool) -> Check:
    path = system.which(tool)
    if path:
        return Check(tool, True, path)
    return Check(tool, False, "not on PATH", fix, blocker)


def _mlx(system: System, needed: bool) -> Check:
    if not needed:
        return Check("mlx-vlm", True, "not needed by the running versions")
    if system.platform != "darwin-arm64":
        detail = f"Qwen3-VL runs through MLX on Apple silicon only; this is {system.platform}"
        return Check("mlx-vlm", False, detail, NO_VLM)
    if not system.installed("mlx_vlm"):
        return Check("mlx-vlm", False, "not installed", SYNC)
    return Check("mlx-vlm", True, "installed, runs Qwen3-VL on the GPU")


def _torch(system: System, needed: bool) -> Check:
    if not needed:
        return Check("torch", True, "not needed by the running versions")
    if not (system.installed("torch") and system.installed("transformers")):
        return Check("torch", False, "torch or transformers not installed", SYNC)
    return Check("torch", True, "installed, runs DINOv2")


def _model(system: System, model_id: str) -> Check:
    name = f"model {model_id}"
    if system.cached(model_id):
        return Check(name, True, "in the local Hugging Face cache")
    return Check(name, False, "not downloaded", f"uv run hf download {model_id}")


def _chat(settings: Settings) -> Check:
    if (settings.chat_ui_dist / "index.html").is_file():
        return Check("chat screen", True, f"built in {settings.chat_ui_dist}")
    detail = "not built; `resourcly serve` serves the API only"
    return Check("chat screen", False, detail, "make chat", blocker=False)
