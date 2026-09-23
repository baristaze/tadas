# Tenancy

The org, the people in it, and the credentials they hold. This is one
of the seven kinds of thing [Tadas is made of](../../../../README.md).

## The nouns

- **Org**: a name, a slug (the short handle that names the org in a
  URL), and a kind. The slug is unique among living orgs. An org is
  personal or team. Every person has exactly one **personal org**, made
  with them: their place to work from the first moment, with a name and
  a slug made for them. Every other org is a **team org**, made on
  purpose. A personal org is otherwise an ordinary org: anyone may be
  added to it, and it holds tasks the way a team org does.
- **Identity**: one person across every org: an email, a password
  kept as a hash, and whether the person is on the operator allowlist
  and what an operator may do there (read, or write, which includes
  read).
- **User**: the identity inside one org: the display name and the
  email the team sees.
- **Membership**: the user's place in the org, with a role.
- **Session**: a signed-in visit. A login is a session with no org
  yet, the one sign-in produces; exchanging it for an org gives a
  session in that org. A live session also proves who the person is,
  so it can list their orgs and be exchanged for a session in another
  one. A session ends at its absolute lifetime or after it sits idle,
  whichever comes first. Only the hash of the token is kept.
- **Second factor**: an operator's TOTP secret, sealed under a key the
  process holds, enrolled once it is confirmed by a first code.
- **Operator token**: an agent's credential for the operator plane.
  One permission, an hour at most, kept as its hash, and good for the
  operator plane alone.
- **API key**: a named, expiring credential for a program, with a
  role. Only the hash is kept; the key is shown once.
- **Socket ticket**: a single-use, short-lived pass for the live
  channel, standing for the session or the API key that asked for it.

## What can happen

- **Sign up.** A person nobody knows yet gives an email, a name, and a
  password, and nothing about an org. The identity, their personal org,
  their user in it, and the owner membership land together, and the
  answer is what a sign-in answers: a login and the one place. The
  personal org is named after the person and its slug is generated from
  that name with a random tail. A held email is refused and nothing
  lands. The email is not verified, by choice. This is how a person
  enters a deployed environment; the seeding below is local only. A
  setting closes it, and then it answers as if it did not exist. The
  password is only this door's: the person and their place are one
  create (`create_person`) that any other way in calls the same way.
- **Create a team org.** A signed-in person names an org, and a slug
  if they want one; otherwise the slug is made from the name. The org,
  their user in it under the name they carry where they are, and the
  owner membership land together, and the answer is their place in it.
  They move there with the switch below. Only a session creates an org;
  an api key is a program's and belongs to its tenant.
- **Sign in.** Email and password give a login that lists the orgs the
  person belongs to, their personal org among them. A person an older
  release made without one gets it at this sign-in. The login is exchanged for a session in one of
  them. An unknown email costs the same time as a wrong password, so
  the answer does not say which emails exist. A run of failed sign-ins
  for one email makes the next one wait, whether or not anyone holds
  the email. A person with a second factor sends the code too.
- **List my orgs, and switch.** A login or a live session lists the
  orgs the person belongs to, a page at a time. Exchanging a live
  session for another org is a switch: the session presented ends in
  the same step that issues the new one, so a person holds one session
  per tab.
- **Sign out.** The session presented is revoked. A person can also
  list their own live sessions in the org and revoke any one of them.
- **Read and change the profile.** The org, the person's own identity,
  and their display name. The email belongs to the identity.
- **Manage members.** List the members a page at a time, change a
  member's role, or remove a member. Removing ends the membership,
  hides the user from every list, and revokes their sessions and API
  keys, all in one step, and announces each revocation so their
  sockets close. A failure lands none of it.
- **Manage API keys.** Create one with a name, a role, and a lifetime
  of at most ninety days; list them (a member manager sees the org's,
  everyone else their own); revoke one. An org on a plan without API
  keys is refused the first one, and a key it already has is kept and
  refused while it is on that plan ([billing](../billing/README.md)).
- **Open the live channel.** Issue a socket ticket; redeem it once.
- **Seed an environment.** Create an org with its first owner, or add
  a person to an org. Both are the platform's own operations, run by
  `make seed` on a local environment; there is no invitation flow yet.
  A person either one makes who did not exist before comes with their
  personal org, in the same commit. The seeding is the platform
  arranging a laptop, not a tenant adding someone, so it is not bound by
  the org's seats, and it grants the seeded team Team.
- **Operate across orgs.** An operator, admitted from the allowlist,
  can create an org with its owner, add a member (bound by the org's
  seats like any other door), read an org, its
  members, its tasks, and its events, read the platform's size, list
  every org, and delete a team org. A personal org is never deleted.
  A deleted org keeps its row as the record; everything else of it is
  purged once the retention has passed. A write operator also resets a person's password, which is
  audited with the operator and the person.
- **Grant an operator.** The grant job puts an identity on the
  allowlist, takes it off, or mints the operator token of the
  provisioner or the smoke identity. Each change of the allowlist is
  audited. The platform's own identities live in a reserved domain,
  which sign-up refuses, and the first grant makes them.
- **Enrol a second factor.** An allowlisted person's first sign-in to
  the operator plane reaches two calls and nothing else: mint the
  secret, then confirm it with a first code. From then on the plane
  admits them only on a sign-in that verified a code.
- **Sweep.** Removed members, revoked or expired keys and sessions,
  spent tickets, and old runs of failed sign-ins are deleted for good
  after the retention, thirty days by default. Erasing a person is this
  purge: the events of this namespace carry ids and never a value.

## The rules

- **The role ladder.** Viewer, member, admin, owner, in that order. A
  viewer reads. A member also writes and manages their own keys. An
  admin and an owner also manage members and the org's plan. The owner ranks above the
  admin although they hold the same permissions today, because the
  owner is the founder and not a permission set.
- **Nothing is issued above the issuer.** An API key's role and a
  granted or changed membership's role are capped at the caller's own
  role. The service role, which the platform's own work runs under, is
  no rung of the ladder: nothing a person mints may carry it.
- **A key never mints a key.** Only a session creates an API key, so
  revoking a leaked key ends every access it gave.
- **Unique among the living.** One slug per living org, one personal
  org per identity, one user per identity in an org, one membership per
  user in an org. Removing a member or deleting an org frees the name
  for reuse.
- **A personal org stays its person's.** It is not deleted, and its
  person is not removed from it and does not change role in it, so it
  never changes hands. Nobody leaves an org by removing themselves, in
  any org. Everyone else in a personal org is an ordinary member.
- **Secrets are fingerprints.** A session token, an API key, and a
  socket ticket are stored as hashes. The plain value is shown once.
- **A ticket works once.** A second redemption is refused.
- **The operator plane takes a second factor or a token.** A session
  proves the person, but it is a tenant's credential, and the operator
  plane refuses it. A person's sign-in admits only when it verified a
  TOTP code; an agent presents an operator token, minted by an
  operator signed in with a code or by the grant job. A token never
  mints a token and never enters a tenant.
- **A code works once.** A TOTP code accepted once is refused after,
  even inside its thirty seconds.
- **A gone org refuses its logins.** Exchanging a login for an org
  that is deleted, or a membership that has ended, is refused as not
  authorized; the login itself still stands.
- **Another org's things do not exist.** A user or a membership that
  belongs to another org is answered exactly like one that never
  existed.
