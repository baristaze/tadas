"""`tadas-ops workos-bootstrap`: the desired state in the repository, a dry
run by default, the authorize probe as the truth of what AuthKit accepts, an
application client whose redirects only the dashboard adds (so the command
never writes the environment's list for it), and a second run against
unchanged config that changes nothing."""

import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from tadas.ops.environments import repository_root
from tadas.ops.workos import desired_file, load_desired, workos_bootstrap_command

KEY = "sk_test_never_printed"
APP = "client_app"
DESIRED = """
staging:
  api_key_variable: WORKOS_API_KEY
  client_id: client_app
  client: application
  redirect_uris:
    - http://localhost:55173/auth/callback
    - https://app.staging.example.test/auth/callback
  login_initiation_uri: https://app.staging.example.test/login
  webhooks: []
"""
# The environment's own client: the one kind whose redirects the API writes.
DESIRED_ENVIRONMENT_CLIENT = DESIRED.replace("client: application", "client: environment")


class FakeWorkOS:
    """The environment's redirect list, and the application's own list the
    authorize probe reads. `mirrored` says whether an environment write
    reaches the application's list; `known` answers a create with 422."""

    def __init__(
        self,
        accepted: set[str],
        *,
        mirrored: bool = True,
        known: set[str] | None = None,
    ) -> None:
        self.accepted = set(accepted)
        self.listed: list[str] = sorted(known or set())
        self.mirrored = mirrored
        self.created: list[str] = []
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/user_management/authorize":
            assert "authorization" not in request.headers
            query = parse_qs(urlsplit(str(request.url)).query)
            assert query["client_id"] == [APP] and query["provider"] == ["authkit"]
            uri = query["redirect_uri"][0]
            where = "/bootstrap" if uri in self.accepted else "/redirect-uri-invalid"
            return httpx.Response(302, headers={"location": f"https://authkit.test{where}"})
        assert request.headers["authorization"] == f"Bearer {KEY}"
        if path == "/user_management/redirect_uris" and request.method == "GET":
            data = [{"object": "redirect_uri", "uri": uri} for uri in self.listed]
            return httpx.Response(200, json={"data": data, "list_metadata": {"after": None}})
        if path == "/user_management/redirect_uris" and request.method == "POST":
            uri = json.loads(request.content)["uri"]
            if uri in self.listed:
                if self.mirrored:
                    self.accepted.add(uri)
                return httpx.Response(422, json={"message": "exists"})
            self.listed.append(uri)
            self.created.append(uri)
            if self.mirrored:
                self.accepted.add(uri)
            return httpx.Response(201, json={"object": "redirect_uri", "uri": uri})
        return httpx.Response(404, json={"message": "no"})


def repo(tmp_path: Path, desired: str = DESIRED) -> Path:
    file = tmp_path / "deployment" / "workos" / "environments.yaml"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(desired)
    return tmp_path


async def run(
    tmp_path: Path,
    api: FakeWorkOS,
    *,
    apply: bool,
    key: str | None = KEY,
    desired: str = DESIRED,
) -> int:
    return await workos_bootstrap_command(
        argparse.Namespace(environment="staging", apply=apply),
        transport=httpx.MockTransport(api),
        environ={} if key is None else {"WORKOS_API_KEY": key},
        root=repo(tmp_path, desired),
    )


def test_the_committed_desired_state_names_both_environments() -> None:
    root = repository_root(Path(__file__).parent)
    assert root is not None
    staging = load_desired(desired_file(root), "staging")
    production = load_desired(desired_file(root), "production")
    assert staging.client_id == "client_01M3640D8WBF9KC0P89YW4E72N"
    assert production.client_id == "client_01M363XVP5FGF2P45FHK9B7MJD"
    assert "http://localhost:55173/auth/callback" in staging.redirect_uris
    assert all(u.startswith("https://") for u in production.redirect_uris)
    assert staging.api_key_variable != production.api_key_variable
    assert staging.webhooks == () and production.webhooks == ()
    assert staging.client == "application" and production.client == "application"


async def test_an_application_client_is_probed_and_its_environment_list_never_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The stray entry in the environment's list is reported and left alone,
    and a missing redirect is a dashboard step even under --apply."""
    stray = "http://localhost:5173/auth/callback"
    api = FakeWorkOS({"http://localhost:55173/auth/callback"}, known={stray})
    assert await run(tmp_path, api, apply=True) == 1
    out = capsys.readouterr().out
    assert "application client client_app" in out
    assert f"environment list: 1 redirect URI(s): {stray}" in out
    assert "AuthKit does not read it for an application; nothing here is written" in out
    assert "https://app.staging.example.test/auth/callback: missing (dashboard)" in out
    assert "Redirects tab of application client_app" in out
    assert "1 redirect URI(s) need the dashboard" in out
    assert not any(r.method == "POST" for r in api.requests)


async def test_an_application_client_passes_once_the_dashboard_holds_every_redirect(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api = FakeWorkOS({"http://localhost:55173/auth/callback"})
    assert await run(tmp_path, api, apply=False) == 1
    capsys.readouterr()
    # The person adds it on the application's Redirects tab.
    api.accepted.add("https://app.staging.example.test/auth/callback")
    assert await run(tmp_path, api, apply=True) == 0
    out = capsys.readouterr().out
    assert "https://app.staging.example.test/auth/callback: present" in out
    assert "nothing to change" in out
    assert not any(r.method == "POST" for r in api.requests)


def test_a_client_kind_the_command_does_not_know_is_refused(tmp_path: Path) -> None:
    repo(tmp_path, DESIRED.replace("client: application", "client: something"))
    with pytest.raises(ValueError, match="client of 'staging' is 'something'"):
        load_desired(desired_file(tmp_path), "staging")


async def test_an_environment_client_dry_run_says_what_it_would_create_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api = FakeWorkOS({"http://localhost:55173/auth/callback"})
    assert await run(tmp_path, api, apply=False, desired=DESIRED_ENVIRONMENT_CLIENT) == 0
    out = capsys.readouterr().out
    assert "http://localhost:55173/auth/callback: present" in out
    assert "https://app.staging.example.test/auth/callback: would create" in out
    assert "1 to create (a dry run; --apply makes them)" in out
    assert not any(r.method == "POST" for r in api.requests)


async def test_an_environment_client_is_created_once_and_the_rerun_changes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api = FakeWorkOS({"http://localhost:55173/auth/callback"})
    assert await run(tmp_path, api, apply=True, desired=DESIRED_ENVIRONMENT_CLIENT) == 0
    first = capsys.readouterr().out
    assert "https://app.staging.example.test/auth/callback: created" in first
    assert api.created == ["https://app.staging.example.test/auth/callback"]
    assert await run(tmp_path, api, apply=True, desired=DESIRED_ENVIRONMENT_CLIENT) == 0
    second = capsys.readouterr().out
    assert api.created == ["https://app.staging.example.test/auth/callback"]
    assert "nothing to change" in second and "created" not in second


async def test_a_redirect_the_list_holds_already_counts_as_present(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The list the read saw may lag a write another run made: the create
    answers 422, and the probe decides."""
    uri = "https://app.staging.example.test/auth/callback"
    api = FakeWorkOS({"http://localhost:55173/auth/callback"})
    original = api.__call__

    def lagging(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            api.listed.append(uri)
        return original(request)

    code = await workos_bootstrap_command(
        argparse.Namespace(environment="staging", apply=True),
        transport=httpx.MockTransport(lagging),
        environ={"WORKOS_API_KEY": KEY},
        root=repo(tmp_path, DESIRED_ENVIRONMENT_CLIENT),
    )
    assert code == 0
    out = capsys.readouterr().out
    assert f"{uri}: present" in out and api.created == []


async def test_a_redirect_only_the_dashboard_adds_fails_the_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api = FakeWorkOS({"http://localhost:55173/auth/callback"}, mirrored=False)
    assert await run(tmp_path, api, apply=True, desired=DESIRED_ENVIRONMENT_CLIENT) == 1
    out = capsys.readouterr().out
    assert "missing (dashboard)" in out and "for client client_app" in out
    # Rerun: the environment's list holds it, so no write is tried again.
    posts = sum(r.method == "POST" for r in api.requests)
    assert await run(tmp_path, api, apply=True, desired=DESIRED_ENVIRONMENT_CLIENT) == 1
    assert sum(r.method == "POST" for r in api.requests) == posts


async def test_the_key_never_appears_in_what_it_prints(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api = FakeWorkOS(set(), mirrored=False)
    await run(tmp_path, api, apply=True)
    await run(tmp_path, api, apply=False)
    captured = capsys.readouterr()
    assert KEY not in captured.out + captured.err
    assert "login initiation URI: https://app.staging.example.test/login" in captured.out
    assert "webhooks: none" in captured.out


async def test_no_key_is_a_usage_error_that_names_the_variable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api = FakeWorkOS(set())
    assert await run(tmp_path, api, apply=False, key=None) == 2
    assert "WORKOS_API_KEY is not set" in capsys.readouterr().err
    assert api.requests == []
