# Becoming an operator

The operator plane reads every tenant, and writes them for a `write`
entry. Getting onto it takes four things, in order: an identity, a
grant, a second factor, and a token. A person does all four; an agent
does none of them, and works from the token the last step writes.

Set the environment first. Staging:

```
API=https://api.staging.tadas.fyi
ENV=staging
```

Production is `https://api.tadas.fyi` and `production`, and its grant
runs on `release` and waits for the deploy's reviewer.

## Sign in

Open the environment's app (`https://app.staging.tadas.fyi`) and sign in
through WorkOS with the email you will operate with. Nothing in the
deployment holds a credential for you, and a first sign-in is the
sign-up: it makes your identity and your personal org, with you as its
owner, a tenant account, which the grant turns into an operator.

## The grant

A person dispatches the workflow on the environment's branch. It runs
`tadas-api grant-operator` as a one-off task under the deploy role, and
the email is masked in the log.

```
gh workflow run grant-operator.yml --ref main -f environment=staging \
  -f email=<your email> -f permission=write        # or read
```

`read` is enough to investigate. `write` also changes a tenant's rows,
and the traffic generator's provisioner is the only identity that needs
it day to day. A person with `write` uses it for one named step, such
as sending a failed work item back (`tadas-ops work requeue`), which
mints a `write` token for that call alone.

## The steps in the terminal

These run in bash and zsh alike (`read -p` is bash only, so each prompt
is printed first). Everything happens in your own terminal: the sign-in
and the code never leave it.

1. **Enrol the second factor.** Until you do, the operator plane admits the enrolment and nothing else. There is no console screen yet, so enrol through the API, in your own terminal. A terminal signs in with the device sign-in: it prints a code and an address, you confirm the code in your browser, and it gets the sign-in.

   ```
   API=https://api.staging.tadas.fyi
   json() { python3 -c "import json,sys; print(json.load(sys.stdin).get('$1', ''))"; }

   sign_in() {  # prints a sign-in credential once you confirm the code
     d=$(curl -s -X POST "$API/v1/auth/device")
     printf 'open %s and confirm %s\n' "$(echo "$d" | json verification_uri_complete)" \
       "$(echo "$d" | json user_code)" >&2
     device=$(echo "$d" | json device_code)
     while :; do
       sleep 5
       t=$(curl -s "$API/v1/auth/device/token" -H 'Content-Type: application/json' \
         -d "{\"device_code\":\"$device\"}" | json token)
       if [ -n "$t" ]; then echo "$t"; return; fi
     done
   }

   with_code() {  # $1 a sign-in credential, $2 a code: the sign-in that verified it
     curl -s "$API/v1/auth/second-factor" -H "Authorization: Bearer $1" \
       -H 'Content-Type: application/json' -d "{\"totp_code\":\"$2\"}" | json token
   }

   TOKEN=$(sign_in)
   curl -s -X POST "$API/v1/admin/me/totp" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
   ```

   The answer carries `otpauth_uri`, once. Add it to an authenticator app: most take the URI pasted, and any QR tool makes a code from it. Then confirm with the first code the app shows:

   ```
   printf 'code: '; read -r CODE
   curl -s -X POST "$API/v1/admin/me/totp/confirm" -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' -d "{\"totp_code\":\"$CODE\"}"; echo
   ```

   It answers `identity_id` and `confirmed_at`. From now on the plane admits you only on a sign-in that verified a code.

2. **Check the fence**, once, while the shell still holds the sign-in (it lasts ten minutes):

   ```
   curl -s -o /dev/null -w 'no code: %{http_code}\n' "$API/v1/admin/orgs" \
     -H "Authorization: Bearer $TOKEN"
   printf 'code: '; read -r CODE
   curl -s -o /dev/null -w 'with code: %{http_code}\n' "$API/v1/admin/orgs" \
     -H "Authorization: Bearer $(with_code "$TOKEN" "$CODE")"
   unset TOKEN
   ```

   A sign-in without a code answers `401` on the plane, and the same sign-in with one answers `200`. A tenant sign-in needs no code; the plane is what demands it.

3. **Write your token into the ops env file**, from the repository: `uv run tadas-ops token --env staging --identity operator`. It shows a code to confirm in your browser, asks for a code from your authenticator, writes `TADAS_OPERATOR_TOKEN` into `~/.config/tadas/ops/staging.env` (mode 600), and prints nothing else. A token lasts an hour; run it again when it runs out. Every ops skill works from that file, so no agent holds your sign-in or your code.

## When a token runs out

A token lasts an hour. Run step 3 again; it asks you to confirm a
sign-in and for a fresh code. Nothing else changes, and the skills pick
up the new value from the file.

## Taking an operator off the plane

```
gh workflow run grant-operator.yml --ref main -f environment=staging \
  -f email=<email> -f permission=none -f disable=true
```

The entry is disabled, the identity keeps its tenant account, and its
operator tokens stop being admitted at their next use.
