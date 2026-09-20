# Tenancy

The org, the people in it, and the credentials they hold. This is one
of the six kinds of thing [Tadas is made of](../../../../README.md).

## The nouns

- **Org**: a name and a slug, the short handle that names the org in
  a URL. The slug is unique among living orgs.
- **Identity**: one person across every org: an email, a password
  kept as a hash, and whether the person is on the operator allowlist
  and what an operator may do there (read, or write, which includes
  read).
- **User**: the identity inside one org: the display name and the
  email the team sees.
- **Membership**: the user's place in the org, with a role.
- **Session**: a signed-in visit. A login is a session with no org
  yet, the one sign-in produces; exchanging it for an org gives a
  session in that org. Only the hash of the token is kept.
- **API key**: a named, expiring credential for a program, with a
  role. Only the hash is kept; the key is shown once.
- **Socket ticket**: a single-use, short-lived pass for the live
  channel, standing for the session or the API key that asked for it.

## What can happen

- **Sign in.** Email and password give a login that lists the orgs the
  person belongs to. The login is exchanged for a session in one of
  them. An unknown email costs the same time as a wrong password, so
  the answer does not say which emails exist.
- **Sign out.** The session presented is revoked. A person can also
  list their own live sessions in the org and revoke any one of them.
- **Read and change the profile.** The org, the person's own identity,
  and their display name. The email belongs to the identity.
- **Manage members.** List the members a page at a time, change a
  member's role, or remove a member. Removing ends the membership,
  hides the user from every list, and revokes their sessions and API
  keys, all in one step.
- **Manage API keys.** Create one with a name, a role, and a lifetime
  of at most ninety days; list them (a member manager sees the org's,
  everyone else their own); revoke one.
- **Open the live channel.** Issue a socket ticket; redeem it once.
- **Seed an environment.** Create an org with its first owner, or add
  a person to an org. Both are the platform's own operations; there is
  no invitation flow yet.
- **Operate across orgs.** An operator, admitted from the allowlist,
  can create an org with its owner, add a member, read an org, its
  members, its tasks, and its events, read the platform's size, list
  every org, and delete an org. A deleted org keeps its row as the
  record; everything else of it is purged once the retention has
  passed.
- **Sweep.** Removed members, revoked or expired keys and sessions,
  and spent tickets are deleted for good after the retention, thirty
  days by default. Erasing a person is this purge.

## The rules

- **The role ladder.** Viewer, member, admin, owner, in that order. A
  viewer reads. A member also writes and manages their own keys. An
  admin and an owner also manage members. The owner ranks above the
  admin although they hold the same permissions today, because the
  owner is the founder and not a permission set.
- **Nothing is issued above the issuer.** An API key's role and a
  granted or changed membership's role are capped at the caller's own
  role. The service role, which the platform's own work runs under, is
  no rung of the ladder: nothing a person mints may carry it.
- **A key never mints a key.** Only a session creates an API key, so
  revoking a leaked key ends every access it gave.
- **Unique among the living.** One slug per living org, one user per
  identity in an org, one membership per user in an org. Removing a
  member or deleting an org frees the name for reuse.
- **Secrets are fingerprints.** A session token, an API key, and a
  socket ticket are stored as hashes. The plain value is shown once.
- **A ticket works once.** A second redemption is refused.
- **A gone org refuses its logins.** Exchanging a login for an org
  that is deleted, or a membership that has ended, is refused as not
  authorized; the login itself still stands.
- **Another org's things do not exist.** A user or a membership that
  belongs to another org is answered exactly like one that never
  existed.
