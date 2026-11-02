"""`resourcly doctor`: one line per check of this machine, a fix for each problem."""

import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from resourcly import doctor
from resourcly.bootstrap import PROJECT_ROOT, Settings
from resourcly.cli import app
from resourcly.doctor import Check, System

QWEN = "mlx-community/Qwen3-VL-8B-Instruct-4bit"
MODELS = {QWEN, "facebook/dinov2-small", "facebook/dinov2-base"}


def mac(cached: set[str] = MODELS, **changes) -> System:
    """An Apple silicon Mac with every tool, both extras and the given models."""
    system = System(
        python=(3, 12),
        platform="darwin-arm64",
        which=lambda tool: f"/usr/bin/{tool}",
        installed=lambda module: True,
        cached=lambda model_id: model_id in cached,
    )
    return replace(system, **changes)


@pytest.fixture
def defaults(settings: Settings, tmp_path: Path) -> Settings:
    """The app's default versions, which run models, and a built chat screen."""
    chat = tmp_path / "chat"
    chat.mkdir()
    (chat / "index.html").write_text("<html></html>")
    return replace(settings, versions=Settings().versions, chat_ui_dist=chat)


def by_name(checks: list[Check]) -> dict[str, Check]:
    return {check.name: check for check in checks}


def test_a_ready_mac_passes_every_check(defaults: Settings) -> None:
    checks = doctor.run(defaults, mac())

    assert [check.name for check in checks if not check.ok] == []
    names = [check.name for check in checks]
    assert names[:5] == ["python", "uv", "node", "mlx-vlm", "torch"]
    assert {f"model {model_id}" for model_id in MODELS} <= set(names)
    assert {"reader", "router", "failure", "answer", "chat screen"} <= set(names)
    assert "probes/dinov2-small-v1.json" in by_name(checks)["router"].detail
    assert "indexes/dinov2-base-v1.json" in by_name(checks)["failure"].detail


def test_a_missing_model_is_a_blocker_with_its_download_command(defaults: Settings) -> None:
    checks = by_name(doctor.run(defaults, mac(cached=MODELS - {"facebook/dinov2-base"})))

    missing = checks["model facebook/dinov2-base"]
    assert (missing.ok, missing.blocker) == (False, True)
    assert missing.fix == "uv run hf download facebook/dinov2-base"
    assert checks[f"model {QWEN}"].ok


def test_a_missing_figure_index_points_to_make_index(defaults: Settings, tmp_path: Path) -> None:
    versions = tmp_path / "versions"
    shutil.copytree(PROJECT_ROOT / "versions", versions)
    (versions / "failure" / "indexes" / "dinov2-base-v1.json").unlink()

    checks = by_name(doctor.run(replace(defaults, versions_dir=versions), mac()))

    failure = checks["failure"]
    assert (failure.ok, failure.blocker) == (False, True)
    assert "indexes/dinov2-base-v1.json" in failure.detail
    assert failure.fix == "make index"
    assert checks["router"].ok


def test_an_unbuilt_chat_screen_is_a_warning_with_the_build_command(
    defaults: Settings, tmp_path: Path
) -> None:
    checks = by_name(doctor.run(replace(defaults, chat_ui_dist=tmp_path / "none"), mac()))

    chat = checks["chat screen"]
    assert (chat.ok, chat.blocker) == (False, False)
    assert chat.fix == "make chat"


def test_model_free_versions_need_no_model_or_extra(settings: Settings) -> None:
    bare = mac(cached=set(), installed=lambda module: False, which=lambda tool: None)

    checks = doctor.run(settings, bare)

    assert not any(check.name.startswith("model ") for check in checks)
    assert [check.name for check in checks if not check.ok and check.blocker] == ["uv"]


def test_a_machine_that_is_not_apple_silicon_cannot_run_the_vision_model(
    defaults: Settings,
) -> None:
    checks = by_name(doctor.run(defaults, mac(platform="linux-x86_64")))

    mlx = checks["mlx-vlm"]
    assert (mlx.ok, mlx.blocker) == (False, True)
    assert "Apple silicon" in mlx.detail
    assert "RESOURCLY_READER_VERSION=textlayer-v0" in mlx.fix


def test_a_missing_extra_says_how_to_install_it(defaults: Settings) -> None:
    checks = by_name(doctor.run(defaults, mac(installed=lambda module: module != "torch")))

    assert checks["torch"].fix == "uv sync --extra vlm --extra router"
    assert checks["mlx-vlm"].ok


def test_the_command_prints_each_fix_and_fails_on_a_blocker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(System, "current", classmethod(lambda cls: mac(cached=set())))
    monkeypatch.delenv("RESOURCLY_READER_VERSION")

    result = CliRunner().invoke(app, ["doctor"])

    assert result.exit_code == 1, result.output
    assert f"fix: uv run hf download {QWEN}" in result.output
    assert "not ready" in result.output


def test_the_command_passes_with_only_warnings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    no_node = mac(which=lambda tool: None if tool == "node" else f"/usr/bin/{tool}")
    monkeypatch.setattr(System, "current", classmethod(lambda cls: no_node))
    monkeypatch.setenv("RESOURCLY_CHAT_UI_DIST", str(tmp_path / "none"))

    result = CliRunner().invoke(app, ["doctor"])

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert any(line.startswith("warn  node") for line in lines), result.output
    assert any(line.startswith("warn  chat screen") for line in lines)
    assert "  fix: make chat" in lines
    assert lines[-1].startswith("ready")


def test_models_lists_what_the_running_versions_need(monkeypatch: pytest.MonkeyPatch) -> None:
    for component in ("READER", "FAILURE", "ANSWER"):
        monkeypatch.delenv(f"RESOURCLY_{component}_VERSION")

    result = CliRunner().invoke(app, ["models"])

    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [QWEN, "facebook/dinov2-small", "facebook/dinov2-base"]
