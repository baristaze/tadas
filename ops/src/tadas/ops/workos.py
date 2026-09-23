"""`tadas-ops workos-bootstrap`: reconciles one WorkOS environment with the
desired state committed in `deployment/workos/environments.yaml`. A dry run
by default; `--apply` writes. Rerun against unchanged config, it changes
nothing and says so.

A redirect URI is present when AuthKit accepts it for the application:
`GET /user_management/authorize` with the application's client id and the
URI answers with a redirect that is not to `/redirect-uri-invalid`. That
probe is the truth, because the application's redirects live on its own
Redirects tab in the WorkOS dashboard, which no API reads or writes. The API
writes one list, the environment's (`/user_management/redirect_uris`); the
command reports it, adds a missing URI to it, and probes again. A URI the
probe still refuses is one only the dashboard can add, and the command says
so and exits 1. The login initiation URI has no API at all: it is printed as
a check to make on the same tab. No webhook is reconciled: the sign-in and
the invitations need none.

The API key comes from the variable the desired state names for the
environment, and never appears in anything this prints."""

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import yaml

from tadas.ops.environments import repository_root

WORKOS_API = "https://api.workos.com"
TIMEOUT_SECONDS = 10.0
INVALID_REDIRECT_PATH = "/redirect-uri-invalid"
OK, FAILED, USAGE = 0, 1, 2


@dataclass(frozen=True)
class Desired:
    environment: str
    api_key_variable: str
    client_id: str
    redirect_uris: tuple[str, ...]
    login_initiation_uri: str
    webhooks: tuple[str, ...]


def desired_file(root: Path | None = None) -> Path:
    top = root or repository_root()
    if top is None:
        raise FileNotFoundError("run workos-bootstrap from inside the repository")
    return top / "deployment" / "workos" / "environments.yaml"


def load_desired(path: Path, environment: str) -> Desired:
    loaded: Any = yaml.safe_load(path.read_text())
    if not isinstance(loaded, dict) or environment not in loaded:
        names = ", ".join(sorted(loaded)) if isinstance(loaded, dict) else "none"
        raise ValueError(f"{path} names no WorkOS environment {environment!r} (it names {names})")
    entry = loaded[environment]
    return Desired(
        environment=environment,
        api_key_variable=str(entry["api_key_variable"]),
        client_id=str(entry["client_id"]),
        redirect_uris=tuple(str(u) for u in entry["redirect_uris"]),
        login_initiation_uri=str(entry["login_initiation_uri"]),
        webhooks=tuple(str(w) for w in entry.get("webhooks") or ()),
    )


class WorkOS:
    """The few WorkOS routes the reconcile reads and writes. The key rides
    the authorization header of the calls that need it and nothing else."""

    def __init__(self, client: httpx.AsyncClient, api_key: str) -> None:
        self._client = client
        self._auth = {"Authorization": f"Bearer {api_key}"}

    async def accepts(self, client_id: str, redirect_uri: str) -> bool:
        """Whether AuthKit accepts the redirect for the application."""
        response = await self._client.get(
            "/user_management/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "provider": "authkit",
            },
        )
        if response.status_code not in (301, 302, 303, 307, 308):
            raise ValueError(
                f"the authorize probe answered {response.status_code} for {redirect_uri}"
            )
        location = response.headers.get("location", "")
        return urlsplit(location).path != INVALID_REDIRECT_PATH

    async def environment_redirects(self) -> list[str]:
        """The environment's own list, every page of it."""
        found: list[str] = []
        after: str | None = None
        while True:
            params: dict[str, str | int] = {"limit": 100}
            if after:
                params["after"] = after
            response = await self._client.get(
                "/user_management/redirect_uris", params=params, headers=self._auth
            )
            answer = self._json(response, "listing the redirect URIs")
            found.extend(str(item["uri"]) for item in answer.get("data", []))
            after = (answer.get("list_metadata") or {}).get("after")
            if not after:
                return found

    async def create_redirect(self, uri: str) -> bool:
        """True when it was created, False when the list held it already (422)."""
        response = await self._client.post(
            "/user_management/redirect_uris", json={"uri": uri}, headers=self._auth
        )
        if response.status_code == 422:
            return False
        self._json(response, f"creating the redirect URI {uri}")
        return True

    @staticmethod
    def _json(response: httpx.Response, doing: str) -> dict[str, Any]:
        if response.is_error:
            # The body, never the request: the request carried the key.
            raise ValueError(f"{doing}: WorkOS answered {response.status_code}")
        body: Any = response.json()
        return body if isinstance(body, dict) else {}


@dataclass
class Outcome:
    lines: list[str]
    created: int = 0
    pending: int = 0
    missing: int = 0

    @property
    def exit_code(self) -> int:
        return FAILED if self.missing else OK


async def reconcile(desired: Desired, workos: WorkOS, *, apply: bool) -> Outcome:
    outcome = Outcome(lines=[])
    listed = await workos.environment_redirects()
    say = outcome.lines.append
    say(f"WorkOS {desired.environment}, application {desired.client_id}")
    say(
        f"environment list: {len(listed)} redirect URI(s)"
        + (f": {', '.join(listed)}" if listed else "")
    )
    for uri in desired.redirect_uris:
        if await workos.accepts(desired.client_id, uri):
            say(f"redirect {uri}: present")
            continue
        if uri in listed:
            # The environment's list holds it and AuthKit still refuses it:
            # a write through the API cannot help.
            outcome.missing += 1
            say(f"redirect {uri}: missing (dashboard): {dashboard(desired)}")
            continue
        if not apply:
            outcome.pending += 1
            say(f"redirect {uri}: would create")
            continue
        created = await workos.create_redirect(uri)
        if await workos.accepts(desired.client_id, uri):
            if created:
                outcome.created += 1
            say(f"redirect {uri}: {'created' if created else 'present'}")
        else:
            outcome.missing += 1
            say(f"redirect {uri}: missing (dashboard): {dashboard(desired)}")
    say(
        f"login initiation URI: {desired.login_initiation_uri} "
        "(check it on the application's Redirects tab; no API reads or writes it)"
    )
    say("webhooks: none" if not desired.webhooks else f"webhooks: {', '.join(desired.webhooks)}")
    say(summary(outcome, apply=apply))
    return outcome


def dashboard(desired: Desired) -> str:
    return (
        f"add it on the Redirects tab of application {desired.client_id} in the WorkOS "
        "dashboard; the API writes only the environment's list, which AuthKit does not "
        "read for this application"
    )


def summary(outcome: Outcome, *, apply: bool) -> str:
    if outcome.missing:
        return f"{outcome.missing} redirect URI(s) need the dashboard"
    if outcome.pending:
        return f"{outcome.pending} to create (a dry run; --apply makes them)"
    if outcome.created:
        return f"created {outcome.created}"
    return "nothing to change"


async def workos_bootstrap_command(
    args: argparse.Namespace,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    environ: dict[str, str] | None = None,
    root: Path | None = None,
) -> int:
    desired = load_desired(desired_file(root), args.environment)
    values = os.environ if environ is None else environ
    api_key = values.get(desired.api_key_variable, "").strip()
    if not api_key:
        print(
            f"tadas-ops: {desired.api_key_variable} is not set; the key of WorkOS "
            f"{desired.environment} is what this command runs with, and there is none here",
            file=sys.stderr,
        )
        return USAGE
    async with httpx.AsyncClient(
        base_url=WORKOS_API,
        timeout=TIMEOUT_SECONDS,
        follow_redirects=False,
        transport=transport,
    ) as client:
        outcome = await reconcile(desired, WorkOS(client, api_key), apply=args.apply)
    for line in outcome.lines:
        print(line)
    return outcome.exit_code
