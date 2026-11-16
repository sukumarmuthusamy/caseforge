"""The package can be installed from a clean checkout (a problem first found by an isolated install)."""

from __future__ import annotations

import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def project() -> dict:
    return tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))


def test_every_file_the_metadata_names_is_inside_the_project():
    """Current setuptools refuses a readme outside the project directory, so `pip install -e .` failed on a clean checkout."""
    readme = project()["project"]["readme"]
    assert not str(readme).startswith(".."), readme
    assert (BACKEND / readme).is_file()


def test_the_data_files_the_package_declares_exist():
    patterns = project()["tool"]["setuptools"]["package-data"]["caseforge"]
    for pattern in patterns:
        assert list((BACKEND / "caseforge").glob(pattern)), f"no file matches package-data {pattern!r}"


def test_serving_beyond_this_machine_is_warned_about():
    from caseforge.__main__ import non_local_warning

    for local in ("127.0.0.1", "localhost", "::1"):
        assert non_local_warning(local) is None
    for exposed in ("0.0.0.0", "192.168.1.20", "example.test"):
        assert "no authentication" in non_local_warning(exposed)
