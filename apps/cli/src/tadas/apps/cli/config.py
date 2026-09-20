"""Where the CLI finds the API and the credential. The environment wins
(`TADAS_API_URL`, `TADAS_TOKEN`), then the session file `tadas login`
writes under `TADAS_HOME` (default `~/.config/tadas`), then the local
default. `TADAS_TOKEN` may hold an api key as well as a session token; the
API accepts either as a bearer. `TADAS_HTTP_TIMEOUT_SECONDS` bounds every
call the client makes."""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 30.0
SESSION_FILE = "session.json"


class BadSetting(ValueError):
    """A setting the environment names cannot be used. That is the caller's
    input, not a failure of the run, so the CLI tells it in one line and
    exits 2, the way it tells any other usage error."""


@dataclass(frozen=True)
class Session:
    api_url: str
    token: str
    email: str
    display_name: str
    org_slug: str
    org_name: str


def home() -> Path:
    override = os.environ.get("TADAS_HOME")
    return Path(override) if override else Path.home() / ".config" / "tadas"


def load_session() -> Session | None:
    path = home() / SESSION_FILE
    try:
        return Session(**json.loads(path.read_text()))
    except OSError, ValueError, TypeError:
        return None


def save_session(session: Session) -> Path:
    """The token is a secret: the file is created owner-only, not created
    readable and locked down after, and so is the directory that holds it.
    A place that will not take the file is TADAS_HOME's doing, so it is told
    as a setting and not as a traceback."""
    path = home() / SESSION_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as file:
            file.write(json.dumps(asdict(session), indent=2) + "\n")
        path.chmod(0o600)  # a file an earlier version left readable
    except OSError as error:
        raise BadSetting(f"the session cannot be kept in {path.parent}: {error}") from None
    return path


def clear_session() -> bool:
    path = home() / SESSION_FILE
    if not path.exists():
        return False
    try:
        path.unlink()
    except OSError as error:
        raise BadSetting(f"the session cannot be forgotten: {error}") from None
    return True


def api_url(option: str | None = None) -> str:
    """`--api`, then the environment, then the session's, then local."""
    if option:
        return option
    if from_env := os.environ.get("TADAS_API_URL"):
        return from_env
    session = load_session()
    return session.api_url if session else DEFAULT_API_URL


def timeout_seconds() -> float:
    """The timeout every call carries: the environment, else the default."""
    raw = os.environ.get("TADAS_HTTP_TIMEOUT_SECONDS")
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        seconds = float(raw)
    except ValueError:
        raise BadSetting(f"TADAS_HTTP_TIMEOUT_SECONDS is not a number: {raw!r}") from None
    if seconds <= 0:
        raise BadSetting(f"TADAS_HTTP_TIMEOUT_SECONDS must be positive: {raw!r}")
    return seconds


def token() -> str | None:
    """The bearer every request carries. It travels in a header, which carries
    ascii and nothing else, so a value that does not is refused here rather
    than encoded at the wire; the value is a secret, so the line names the
    variable and never what is in it."""
    if from_env := os.environ.get("TADAS_TOKEN"):
        if not from_env.isascii():
            raise BadSetting("TADAS_TOKEN has characters a request header cannot carry")
        return from_env
    session = load_session()
    return session.token if session else None
