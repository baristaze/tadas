"""The ops skills share one preamble, and keep their invariants inline.

The operational detail a reader needs once, and not in every skill, lives
in `.claude/skills/_shared/ops-preamble.md`: the profiles, the account
check, the env file's fields, and the way back when a token expires. A
skill that reaches a cloud environment names that file.

A rule that must never be missed does not travel by reference, so the
lines that stop a secret leaking stay written in each skill that could
break them, and this test holds them there.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / ".claude" / "skills"
PREAMBLE = SKILLS / "_shared" / "ops-preamble.md"
README = ROOT / "ops" / "README.md"
REFERENCE = ".claude/skills/_shared/ops-preamble.md"

# Every skill that can reach an environment, and so holds a credential.
READERS = [
    "audit-deploy-time",
    "audit-retention",
    "ops-cloud-deployment-create",
    "ops-cloud-deployment-nuke",
    "ops-infra-as-code",
    "ops-investigate",
    "ops-root-cause",
    "ops-simulate-traffic",
    "ops-watch",
    "stress-test-run",
]
# The skills that reach the env file's tokens.
TOKEN_HOLDERS = [
    "ops-investigate",
    "ops-root-cause",
    "ops-simulate-traffic",
    "ops-watch",
    "stress-test-run",
]
# The skills that read an environment under the investigate profile.
INVESTIGATORS = [*TOKEN_HOLDERS, "ops-infra-as-code", "audit-deploy-time", "audit-retention"]
# The skills that run under an account's administrator.
ADMINISTRATORS = ["ops-cloud-deployment-create", "ops-cloud-deployment-nuke"]
# The audits: read-only analyses that write a report and propose tickets.
AUDITS = [
    "audit-credential-lifetimes",
    "audit-database-calls",
    "audit-deploy-time",
    "audit-provider-calls",
    "audit-query-indexes",
    "audit-retention",
]
# The audits that build a database of their own on the local stack.
DATABASE_AUDITS = [
    "audit-credential-lifetimes",
    "audit-database-calls",
    "audit-provider-calls",
    "audit-query-indexes",
    "audit-retention",
]
SKILL_DIR = re.compile(r"\$\{CLAUDE_SKILL_DIR\}/([^\s`'\")]+)")


def _skill(name: str) -> str:
    return (SKILLS / name / "SKILL.md").read_text()


def _prose(name: str) -> str:
    """The skill's text as one line: a rule is a sentence, wrapped where the
    margin falls, and the margin is not what this test is about."""
    return " ".join(_skill(name).split())


def _allowed_tools(name: str) -> str:
    _, frontmatter, _ = _skill(name).split("---", 2)
    return str(yaml.safe_load(frontmatter).get("allowed-tools", ""))


def test_the_shared_preamble_exists_and_holds_what_moved_into_it() -> None:
    text = PREAMBLE.read_text()
    assert "deployment/cloud/environments.json" in text
    assert "aws sts get-caller-identity" in text
    assert "~/.config/tadas/ops/<env>.env" in text
    assert "TADAS_PROVISIONER_TOKEN" in text
    assert "tadas-<env>-investigate" in text


@pytest.mark.parametrize("name", READERS)
def test_every_skill_that_holds_a_credential_reads_the_preamble(name: str) -> None:
    """The reference is the skill's first instruction, before its steps."""
    text = _skill(name)
    assert REFERENCE in text, f"{name} drops the reference to the shared preamble"
    assert text.index(REFERENCE) < text.index("## Input")


def test_the_skills_that_hold_a_credential_are_the_ones_that_can_call_aws() -> None:
    """A new ops skill that reaches the cloud joins the list above, or this
    fails: the preamble is not optional for a skill that holds a
    credential."""
    reaches_the_cloud = sorted(
        path.parent.name
        for path in SKILLS.glob("*/SKILL.md")
        if "Bash(aws:*)" in _allowed_tools(path.parent.name)
    )
    assert reaches_the_cloud == sorted(READERS)


def test_the_scenario_writer_holds_no_credential_and_needs_no_preamble() -> None:
    text = _prose("stress-test-create-or-update")
    assert "No cloud, no credential, no secret." in text
    assert REFERENCE not in text


@pytest.mark.parametrize("name", TOKEN_HOLDERS)
def test_the_secret_rules_stay_inline(name: str) -> None:
    text = _prose(name)
    assert "Never read the env file" in text
    assert "Never print a token." in text


@pytest.mark.parametrize("name", INVESTIGATORS)
def test_the_refusal_of_a_wider_profile_stays_inline(name: str) -> None:
    assert "Refuse any profile wider than the investigate role." in _prose(name)


@pytest.mark.parametrize("name", ADMINISTRATORS)
def test_the_refusal_of_anything_but_the_administrator_stays_inline(name: str) -> None:
    assert "Refuse any profile but the environment's administrator" in _prose(name)


def test_the_audits_are_the_skills_named_for_one() -> None:
    assert sorted(p.parent.name for p in SKILLS.glob("audit-*/SKILL.md")) == AUDITS


@pytest.mark.parametrize("name", [*AUDITS, "tickets-triage"])
def test_an_audit_reports_and_never_changes_the_code(name: str) -> None:
    text = _prose(name)
    assert "Never modifies a tracked file, never commits, never opens a pull request" in text
    assert f"~/Downloads/tadas_{name.removeprefix('audit-').replace('-', '_')}" in text or (
        name == "tickets-triage" and "~/Downloads/tadas_ticket_triage_" in text
    )
    for section in ("## Input", "## Role and credential", "## Procedure", "## What it never does"):
        assert section in _skill(name), f"{name} has no {section}"
    assert "## Output" in _skill(name)


def _readme_needs(name: str) -> str:
    """What `ops/README.md` says a skill needs: its "Needs" cell, a note in parentheses left out."""
    row = re.search(rf"^\| `{re.escape(name)}` \| ([^|]+) \|", README.read_text(), re.MULTILINE)
    assert row, f"ops/README.md has no row for {name}"
    return re.sub(r"\([^)]*\)", "", row.group(1)).strip().lower()


@pytest.mark.parametrize("name", AUDITS)
def test_an_audit_holds_the_one_role_ops_readme_gives_it(name: str) -> None:
    """An audit opens its Role and credential section with its role, and
    ops/README.md names the same one, so a reader who trusts either grants
    the same credential."""
    section = _skill(name).split("## Role and credential", 1)[1].strip()
    said = re.split(r"[,.]", section, maxsplit=1)[0].strip().lower()
    needs = _readme_needs(name)
    assert "," not in needs, f"ops/README.md gives {name} more than one role: {needs}"
    assert said == needs


@pytest.mark.parametrize("name", AUDITS)
def test_an_audit_writes_to_no_shared_database_and_no_environment(name: str) -> None:
    text = _prose(name)
    assert "Never writes to" in text and "an environment" in text
    assert "proposed ticket" in text.lower()


@pytest.mark.parametrize("name", DATABASE_AUDITS)
def test_a_database_audit_builds_its_own_database_and_drops_it(name: str) -> None:
    text = _prose(name)
    run = f"audit_{name.removeprefix('audit-').replace('-', '_')}_<yyyymmdd>"
    assert f"uv run python ops/audit/auditdb.py create {run}" in text
    assert f"uv run python ops/audit/auditdb.py drop {run}" in text
    assert "it logs in only to the database it made on the local stack, and drops it" in text


# Every loop an agent runs in a skill, stated with its count and with what the
# skill does when the count is reached. A strong model keeps going until
# something stops it, and a clock alone stops nothing before the session runs
# out, so a rewrite that drops a count fails here.
COUNT_BOUNDS = {
    "ops-watch": [
        "at least 30 seconds",
        "A shorter interval is raised to 30 seconds",
        "A watch runs at most 30 batches.",
        "the interval is widened to `--for` divided by 30, up to five minutes",
        "an hour asked at 10 seconds runs 30 batches of two minutes",
        "its report names the part of the window it did not watch",
        "A batch makes at most 20 tool calls.",
        "A read that would be the 21st call is not made",
        "with `k` from 0 to at most 29",
        "The `--period` passed to `get-metric-data` is a whole minute",
        "The sub-agent names its Next and never runs it",
        "A session follows at most 2 hops of Next.",
        "never more than 30 batches, never a batch shorter than 30 seconds, "
        "never more than 20 tool calls in a batch",
    ],
    "ops-root-cause": [
        "A run follows at most 5 request ids, one pass each",
        "It lists every id past the fifth as not followed",
        "Poll `get-query-results` at most 10 times for one query, each poll after `sleep 5`",
        'writes its log leg as "not read: the query did not finish in 10 polls"',
        "Probe with `limit=1`",
        'the pass ends with "not found" for its id',
        "never more than 5 request ids, never a second pass over one, "
        "never more than 10 polls of a query",
    ],
    "ops-investigate": [
        "Poll `get-query-results` at most 10 times for one query, each poll after `sleep 5`",
        'as "not read: the query did not finish in 10 polls"',
        "Step 8's query is polled the same way.",
        "A session follows at most 2 hops of Next.",
        "never more than 10 polls of a query",
    ],
    "stress-test-run": ["A session follows at most 2 hops of Next."],
    "ops-cloud-deployment-create": ["Its Next is the person's to run, never the session's"],
    "stress-test-create-or-update": ["Its Next is the person's to run, never the session's"],
    "audit-database-calls": ["the first run plus at most 1 rerun"],
}
# The skills whose report's Next a person runs: no session follows it.
PERSONS_NEXT = ["ops-cloud-deployment-create", "stress-test-create-or-update"]
# The skills that wait between two reads with `sleep`.
SLEEPERS = ["ops-investigate", "ops-root-cause", "ops-watch"]


@pytest.mark.parametrize(
    ("name", "bound"), [(name, bound) for name, bounds in COUNT_BOUNDS.items() for bound in bounds]
)
def test_every_loop_a_skill_runs_states_its_count(name: str, bound: str) -> None:
    assert bound in _prose(name), f"{name} no longer says: {bound}"


@pytest.mark.parametrize("name", PERSONS_NEXT)
def test_a_next_that_is_the_persons_is_never_counted_as_a_hop(name: str) -> None:
    assert "hops of Next" not in _prose(name)


@pytest.mark.parametrize("name", SLEEPERS)
def test_a_skill_that_waits_between_polls_may_sleep(name: str) -> None:
    assert "Bash(sleep:*)" in _allowed_tools(name)


def test_triage_closes_nothing_without_the_persons_word() -> None:
    text = _prose("tickets-triage")
    assert "Never closes a ticket without `--apply` and the person's word in this session" in text


@pytest.mark.parametrize("name", sorted(p.parent.name for p in SKILLS.glob("*/SKILL.md")))
def test_every_reference_resolves_and_every_reference_file_is_named_by_a_step(name: str) -> None:
    """A skill keeps its spine and names its detail: a file beside SKILL.md
    is read by the step that names it, so one no step names is an orphan."""
    folder = SKILLS / name
    body = _skill(name)
    for ref in SKILL_DIR.findall(body):
        assert (folder / ref).resolve().exists(), f"{name}: {ref} does not exist"
    procedure = body.split("## Procedure", 1)[-1].split("\n## ", 1)[0]
    for extra in folder.rglob("*.md"):
        if extra.name == "SKILL.md":
            continue
        relative = extra.relative_to(folder).as_posix()
        assert f"${{CLAUDE_SKILL_DIR}}/{relative}" in procedure, f"{name}: no step names {relative}"
