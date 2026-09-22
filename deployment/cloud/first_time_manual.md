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
TadasBootstrapAdmins
```

Add `baris.taze` to both during initial setup.

## 10. Create permission sets

Normal development access:

```text
Permission set: PowerUserAccess
AWS managed policy: PowerUserAccess
Session duration: 12 hours
```

Temporary bootstrap access:

```text
Permission set: TadasBootstrapAdmin
AWS managed policy: AdministratorAccess
Session duration: 1 hour
```

`PowerUserAccess` is insufficient for some initial IAM operations, which is why the temporary bootstrap permission exists.

## 11. Assign access to Tadas accounts

Assign to both `tadas-staging` and `tadas-prod`:

```text
TadasPowerUsers
  -> PowerUserAccess

TadasBootstrapAdmins
  -> TadasBootstrapAdmin
```

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
  TadasBootstrapAdmin

tadas-prod
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

Create these four profiles, all sharing the same `tadas` SSO session:

```text
tadas-staging
tadas-staging-admin
tadas-prod
tadas-prod-admin
```

Current Tadas account IDs:

```text
tadas-staging: 792394000601
tadas-prod:    557092275199
```

Normal profiles use:

```text
PowerUserAccess
```

Admin profiles use:

```text
TadasBootstrapAdmin
```

Default workload region:

```text
us-west-2
```

## 16. Verify profiles

```bash
aws sts get-caller-identity --profile tadas-staging
aws sts get-caller-identity --profile tadas-prod
aws sts get-caller-identity --profile tadas-staging-admin
aws sts get-caller-identity --profile tadas-prod-admin
```

Expected account IDs:

```text
tadas-staging -> 792394000601
tadas-prod    -> 557092275199
```

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
