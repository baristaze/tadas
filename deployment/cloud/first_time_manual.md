# AWS First-Time Setup Manual

This is the bootstrap pattern used for Tadas. The goal is to keep projects and environments isolated, avoid daily root usage, and use temporary SSO credentials instead of long-lived AWS access keys.

## 1. Target structure

```text
AWS Organization
|
+-- Management account
|   +-- AWS Organizations
|   +-- IAM Identity Center
|   +-- Billing
|   +-- No application workloads
|
+-- Tadas OU
    +-- tadas-staging AWS account
    +-- tadas-prod AWS account
```

The AWS account is the main isolation boundary. Staging and production should therefore be separate AWS accounts.

## 2. Root account

Use the AWS root account only for initial bootstrap and operations that explicitly require root.

Do:

- Enable MFA on root.
- Do not create root access keys.
- Do not use root for normal AWS work.
- Keep application resources out of the management account.

## 3. Create AWS Organization

From the original AWS account:

1. Open **AWS Organizations**.
2. Create an organization.
3. Use the default **All features** mode.

The original account becomes the **management account**.

## 4. Enable IAM Identity Center

1. Open **IAM Identity Center**.
2. Enable an **Organization instance**.
3. Multi-account permissions should be enabled.
4. Record the AWS Access Portal URL.

For Tadas, IAM Identity Center is in:

```text
us-east-2
```

This does not determine the region where application infrastructure runs.

## 5. Create the normal human user

Create an IAM Identity Center user such as:

```text
baris.taze
```

This is separate from the AWS root user, even if both use the same email address.

Do not encode roles or projects in the username.

Require MFA for every Identity Center sign-in: **Settings / Authentication / Multi-factor authentication**, set to prompt on every sign-in, and register an authenticator for the user. The admin permission sets are only as strong as that sign-in.

## 6. Create organization admin access

Create group:

```text
OrgAdmins
```

Add:

```text
baris.taze
```

Create or use permission set:

```text
AdministratorAccess
Session duration: 1 hour
```

Assign:

```text
Management account
  OrgAdmins -> AdministratorAccess
```

After this works through the AWS Access Portal, stop using root for normal administration.

## 7. Create Tadas accounts

Create an OU:

```text
Tadas
```

Inside it create two AWS accounts:

```text
tadas-staging
tadas-prod
```

Each AWS account requires a unique email address. Plus-style aliases are convenient, for example:

```text
<you>+aws-tadas-staging@<mail domain>
<you>+aws-tadas-prod@<mail domain>
```

These are the accounts' root addresses. Keep the real ones out of the repository.

Keep the default Organizations access role name:

```text
OrganizationAccountAccessRole
```

## 8. Centralize member-account root management

In AWS Organizations / IAM, enable:

- Root credentials management
- Privileged root actions in member accounts

A delegated administrator is not necessary for this small setup.

## 8a. Turn on Cost Explorer

From the management account, open **Billing and Cost Management** and launch **Cost Explorer**. Member accounts can read it only after this, and it can take up to a day to become available.

The bootstrap's cost anomaly monitor needs it. Until it answers, `scripts/cloud_create.sh` leaves the monitor out and says so; the budget is created either way.

## 9. Create Tadas access groups

Create Identity Center groups:

```text
TadasPowerUsers
TadasReaders
TadasBootstrapAdmins
```

Add `baris.taze` to all three during initial setup.

## 10. Create permission sets

Normal development access:

```text
Permission set: PowerUserAccess
AWS managed policy: PowerUserAccess
Session duration: 12 hours
```

Read-only access, the default in production and for inspection in staging:

```text
Permission set: ReadOnlyAccess
AWS managed policy: ReadOnlyAccess
Inline policy: sts:AssumeRole on arn:aws:iam::*:role/tadas-investigate-*
Session duration: 12 hours
```

A person reads production and hands an agent the investigate role; every change to production is a pull request and a release. The investigate role trusts the account, narrowed by a condition to this permission set's role, so the sign-in itself must be allowed to call `sts:AssumeRole`. The managed `ReadOnlyAccess` policy does not allow it. The inline policy is what lets the `tadas-production-investigate` profile chain from this sign-in; without it the chain answers `AccessDenied`.

Temporary bootstrap access:

```text
Permission set: TadasBootstrapAdmin
AWS managed policy: AdministratorAccess
Session duration: 1 hour
```

`PowerUserAccess` is insufficient for some initial IAM operations, which is why the temporary bootstrap permission exists.

## 11. Assign access to Tadas accounts

Assign to `tadas-staging`:

```text
TadasPowerUsers
  -> PowerUserAccess

TadasReaders
  -> ReadOnlyAccess

TadasBootstrapAdmins
  -> TadasBootstrapAdmin
```

Assign to `tadas-prod`:

```text
TadasReaders
  -> ReadOnlyAccess

TadasPowerUsers
  -> PowerUserAccess

TadasBootstrapAdmins
  -> TadasBootstrapAdmin
```

`PowerUserAccess` in production is for a change that is explicitly authorized, never for everyday work.

The investigate role in each account trusts the permission set `deployment/cloud/environments.json` names for it (`sso_role_name`): `PowerUserAccess` in staging, `ReadOnlyAccess` in production.

The management account should only receive organization-level admin access:

```text
OrgAdmins
  -> AdministratorAccess
```

Do not assign `TadasPowerUsers` to the management account.

## 12. Expected AWS Access Portal

The user should see approximately:

```text
Management account
  AdministratorAccess

tadas-staging
  PowerUserAccess
  ReadOnlyAccess
  TadasBootstrapAdmin

tadas-prod
  ReadOnlyAccess
  PowerUserAccess
  TadasBootstrapAdmin
```

## 13. Install AWS CLI

On macOS with Homebrew:

```bash
brew install awscli
aws --version
```

## 14. Configure AWS CLI with SSO

Do not manually create or copy long-lived access keys.

Run:

```bash
aws configure sso
```

Use:

```text
SSO session name: tadas
SSO start URL: <AWS Access Portal URL>
SSO region: us-east-2
SSO registration scopes: sso:account:access
Default client region: us-west-2
```

For the first profile choose:

```text
Account: tadas-staging
Role: TadasBootstrapAdmin
Profile: tadas-staging-admin
```

## 15. Recommended local profiles

Create these six profiles, all sharing the same `tadas` SSO session:

```text
tadas-staging
tadas-staging-ro
tadas-staging-admin
tadas-prod
tadas-prod-power
tadas-prod-admin
```

Current Tadas account IDs:

```text
tadas-staging: 792394000601
tadas-prod:    557092275199
```

Each profile's role, and what it is for:

```text
tadas-staging     -> PowerUserAccess      normal staging work
tadas-staging-ro  -> ReadOnlyAccess       inspection only
tadas-staging-admin -> TadasBootstrapAdmin  temporary bootstrap and IAM-heavy setup only
tadas-prod        -> ReadOnlyAccess       the default production profile, inspection only
tadas-prod-power  -> PowerUserAccess      only when explicitly authorized
tadas-prod-admin  -> TadasBootstrapAdmin  emergency or bootstrap only, never unless explicitly authorized
```

`tadas-prod` is read-only on purpose: the profile a command reaches production with by default can change nothing.

Default workload region:

```text
us-west-2
```

## 16. Verify profiles

```bash
aws sts get-caller-identity --profile tadas-staging
aws sts get-caller-identity --profile tadas-staging-ro
aws sts get-caller-identity --profile tadas-staging-admin
aws sts get-caller-identity --profile tadas-prod
aws sts get-caller-identity --profile tadas-prod-power
aws sts get-caller-identity --profile tadas-prod-admin
```

Expected account IDs:

```text
tadas-staging*  -> 792394000601
tadas-prod*     -> 557092275199
```

Check that the read-only sign-in may chain to the investigate role. The role name in the output carries the permission set's name, `AWSReservedSSO_ReadOnlyAccess_<suffix>`:

```bash
aws iam list-roles --profile tadas-prod \
  --path-prefix /aws-reserved/sso.amazonaws.com/ \
  --query 'Roles[?contains(RoleName, `ReadOnlyAccess`)].RoleName' --output text
aws iam list-role-policies --profile tadas-prod --role-name <that role>
```

The second command lists `AwsSSOInlinePolicy` once the inline policy of section 10 is on the permission set. An empty list means the investigate profile cannot chain yet.

## 17. Rules for agents and automation

Use explicit profiles. Do not rely on a global/default AWS profile.

Normal work by a person:

```bash
AWS_PROFILE=tadas-staging <command>
```

Normal work by an agent runs under the read-only investigate profile the create run writes, chained from the person's signed-in session. The ops skills refuse the PowerUser and admin profiles as wider than they need:

```bash
AWS_PROFILE=tadas-staging-investigate <command>
```

Initial bootstrap only:

```bash
AWS_PROFILE=tadas-staging-admin <command>
```

Rules:

- Start with staging.
- Never deploy application workloads into the management account.
- Never create long-lived AWS access keys unless there is an exceptional documented requirement.
- Use Infrastructure as Code for persistent infrastructure.
- Prefer the repository's existing IaC convention; otherwise use Terraform.
- Verify `sts get-caller-identity` before every apply/deploy.
- Verify the account ID matches the intended environment.
- Never infer production from a default profile.
- Do not deploy to production until staging is reproducible and reviewed.
- Use GitHub Actions OIDC for CI/CD instead of static AWS secrets.
- Use bootstrap admin only when normal PowerUser access cannot perform the required IAM/bootstrap operation.

## 18. Desired steady state

Human interactive access:

```text
AWS Access Portal
  -> IAM Identity Center
  -> temporary account role
```

Local agent access:

```text
aws sso login
  -> named AWS_PROFILE
  -> temporary credentials
```

CI/CD access:

```text
GitHub Actions
  -> OIDC
  -> dedicated AWS deployment role
```

Avoid this pattern:

```text
Permanent AWS_ACCESS_KEY_ID
Permanent AWS_SECRET_ACCESS_KEY
```

If the shell profile exports either, remove the export. Terraform prefers exported keys to `--profile`, so an exported key silently decides which account a command reaches. The create and nuke scripts clear them for their own run and say so.

## 18a. Cloudflare token for the delegation

`tadas.fyi` is registered at Cloudflare, and its zone stays there. The create run writes one NS record per public name to delegate it to Route 53. Create an API token with **Zone / DNS / Edit** on the `tadas.fyi` zone only, and pass it as an environment variable for the run:

```bash
export CLOUDFLARE_API_TOKEN=<token>
```

Nothing else needs it; CI never does.

## 19. Bootstrap, then hand the admin back

The bootstrap is the `ops-cloud-deployment-create` skill, which runs `scripts/cloud_create.sh`, one account at a time, dry run first:

1. `--env staging` under `tadas-staging-admin`: staging's account and its first deploy.
2. `--env production` under `tadas-prod-admin`: production's account, no release yet.
3. `--env staging` again: it finds production's artifacts bucket and turns replication on.

The first release is a commit merged to `main` after step 3.

After the deploy roles work, remove `baris.taze` from `TadasBootstrapAdmins`, so no one holds `TadasBootstrapAdmin` day to day. Add it back for a run that needs it, such as a destroy or a change to a bootstrap root, and remove it again after.
