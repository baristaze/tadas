# The ops preamble

Every ops skill that reaches a cloud environment reads this page
before its first step. It says which credentials exist, how a skill
checks the one it holds, what the env file keeps, and how a command
uses a value from it without showing it.

The rules that stop a secret leaking are stated in the skills
themselves, one line each, because a skill must not need this page to
be safe. What is here is the detail behind them: the profiles, the
commands, the fields, and the way back when a token is gone.

## The environments file

`deployment/cloud/environments.json` names each environment: the
account id, the region, the administrator profile, the Identity Center
profile an operator signs in with, and the three public names. Read it;
never guess a value it holds.

## The profiles

| Profile | Who holds it | What it is for |
|---------|--------------|----------------|
| `tadas-<env>-investigate` | every skill that reads an environment | assumes `tadas-investigate-<env>`: describes and queries, writes nothing |
| `tadas-staging`, `tadas-prod` | the person signing in | the Identity Center sign-in the investigate profile chains from (PowerUserAccess, ReadOnlyAccess) |
| `tadas-staging-admin`, `tadas-prod-admin` | the account's administrator | the bootstrap and the destroy, by hand, once |

A wider credential is not a convenience; it is the boundary gone. A
skill that reads holds the investigate profile and refuses the rest:
the administrator profiles above all, and the sign-in profiles with
them, whose permission sets are wider than the role.

## The check, before any other command

```bash
aws sts get-caller-identity --profile tadas-<env>-investigate
```

`Arn` reads
`arn:aws:sts::<account>:assumed-role/tadas-investigate-<env>/...`, and
`Account` equals the environment's `account_id` in
`deployment/cloud/environments.json` (read the file; the value is
`.environments.<env>.account_id`). Stop on a mismatch: the right role
in the wrong account is the wrong credential. Every `aws` command a
skill runs carries `--profile tadas-<env>-investigate`; `AWS_PROFILE`
is never read as a substitute.

A skill that runs as an account's administrator checks the same two
answers under that profile:

```bash
aws sts get-caller-identity --profile <admin_profile>
```

`Account` is the environment's `account_id`, and `Arn` is an Identity
Center administrator role (`assumed-role/AWSReservedSSO_...`), never
`assumed-role/tadas-investigate-*`. When the session has expired, the
person signs in again with `aws sso login --profile <admin_profile>`;
the agent never does it for them.

## The env file

`~/.config/tadas/ops/<env>.env` is owner-only and outside the
repository. It holds:

- `TADAS_API_URL`, the environment's edge.
- `TADAS_OPERATOR_TOKEN`, a `read` operator token.
- `TADAS_PROVISIONER_TOKEN`, the file's one `write` token, which
  belongs to the traffic generator alone.
- `TADAS_ERROR_TRACKER_URL` and `TADAS_ERROR_TRACKER_TOKEN`, left
  empty by an environment that names no tracker: nothing provisions
  one. A skill that finds them empty reports "not read", never "no
  errors".
- `TADAS_ERROR_TRACKER_ORG` and `TADAS_ERROR_TRACKER_PROJECT`, which
  name the product's one project and hold the same value in every
  environment: one project takes every environment's errors, and a
  read of it filters on `environment:<env>`.

`local.env`, when there is one, points at the compose stack and adds
the twins, `TADAS_PROMETHEUS_URL` and `TADAS_JAEGER_URL`, on the ports
`.env` names.

The file holds no password and no TOTP secret: an agent never signs in
with a password.

## Using a value without showing it

The file's values stay out of the conversation, so no skill reads it,
with `Read`, `cat`, or anything else. Shell state does not persist
between calls, so a command that needs a value sources the file and
makes the call in the same command:

```bash
set -a; . ~/.config/tadas/ops/<env>.env; set +a
curl -s -H "Authorization: Bearer $TADAS_OPERATOR_TOKEN" "$TADAS_API_URL/v1/admin/me"
```

`tadas-ops` reads the file itself from `--env`, and refuses a file its
group or anyone else can read. No token is printed, by a skill or by
it.

## When a token is refused or expired

A token carries one permission and expires within the hour, and a
person can end it sooner: `uv run tadas-ops token --env <env> --list`
and `--revoke <id>`. A revoked token is refused like an expired one. A
skill never lists or revokes a token: ending a credential is the
person's step, as minting one is.

The operator's: stop and ask the person to run `uv run tadas-ops token
--env <env> --identity operator` in their own terminal, which signs
them in there and asks there for the TOTP code; never ask for the
sign-in or the code in the conversation.

The provisioner's: stop and ask the person to refresh it, in the cloud
by dispatching `grant-operator.yml` with `mint_token: provisioner`,
then running `uv run tadas-ops token --env <env> --identity
provisioner` in their own terminal, which copies the token the grant
job wrote under their own sign-in (in production with `--profile
tadas-prod-power`), never under an investigate profile, which reads no
secret. Locally, a run without a provisioner token in `local.env`
takes `--orgs 0`.
