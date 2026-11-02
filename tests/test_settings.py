from resourcly.bootstrap import PROJECT_ROOT, Settings


def test_the_eval_data_defaults_to_the_evals_folder_and_the_versions_to_the_root() -> None:
    settings = Settings()

    assert settings.gold_dir == PROJECT_ROOT / "evals" / "gold"
    assert settings.versions_dir == PROJECT_ROOT / "versions"
    assert settings.splits_path == PROJECT_ROOT / "evals" / "splits.toml"


def test_the_app_runs_the_layered_router_and_model_free_reader_and_finder_by_default() -> None:
    assert Settings().versions == {
        "reader": "textlayer-v0",
        "router": "three-layer-v1",
        "failure": "shuffled-v0",
    }
    assert Settings.from_env().versions == Settings().versions


def test_the_environment_can_pick_the_versions(monkeypatch) -> None:
    monkeypatch.setenv("RESOURCLY_READER_VERSION", "my-reader-v1")
    monkeypatch.setenv("RESOURCLY_ROUTER_VERSION", "my-router-v1")

    monkeypatch.setenv("RESOURCLY_ROUTER_VERSION", "my-router-v1")
    monkeypatch.setenv("RESOURCLY_FAILURE_VERSION", "my-finder-v1")

    assert Settings.from_env().versions == {
        "reader": "my-reader-v1",
        "router": "my-router-v1",
        "failure": "my-finder-v1",
    }


def test_the_environment_can_move_the_splits_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RESOURCLY_SPLITS", str(tmp_path / "splits.toml"))

    assert Settings.from_env().splits_path == tmp_path / "splits.toml"
