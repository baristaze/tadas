"""The session file holds a token, so it is owner-only from the moment it
exists: created with mode 0600, in a directory created with mode 0700, not
made readable first and locked down after."""

import os
from pathlib import Path

import pytest

from tadas.apps.cli import config


def test_the_session_file_is_owner_only_from_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TADAS_HOME", str(tmp_path / "home" / "tadas"))
    # A chmod after the write is too late to count; the mode must be right at creation.
    monkeypatch.setattr(Path, "chmod", lambda self, mode, **kwargs: None)
    session = config.Session(
        api_url="http://test",
        token="sess_secret",
        email="ann@example.test",
        display_name="Ann",
        org_slug="acme",
        org_name="Acme",
    )
    previous = os.umask(0o022)
    try:
        path = config.save_session(session)
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
        # Saving again truncates and rewrites the same owner-only file.
        path = config.save_session(session)
        assert path.stat().st_mode & 0o777 == 0o600
    finally:
        os.umask(previous)
    assert config.load_session() == session
