# Stress tests

A stress test is the traffic generator at a profile, with a duration, a
ramp, and a target stated before the run. It drives the edge the way a
client does and reads the signals back when it ends.

## The session

Each person signs in once per run, by the local sign-in, and out once at
the end. A session opens the realtime channel, lists the open tasks, adds
five or six, edits one, completes two, reopens one, moves one, lists the
done ones, deletes one, reads the events, and waits to see its own change
on the socket. A person thinks between steps.

The people of an org share its open list. A write that meets a task
changed under it, by a reminder or by the sweep's respace of a run of
ranks, gets a 412, the API's optimistic concurrency: the session reads the
task afresh and writes once more, as a client does, and a task found gone
is dropped. The report counts both on their own, as conflicts and as tasks
gone; neither is an error or a failed session, and every other refusal
still is.

## The target

A p95 and an error ratio, stated in the file or on the run with
`--p95-ms` and `--error-ratio`. The p95 judges the working requests; the
sign-ins and sign-outs are reported beside it. After the run the
platform's own request and 5xx counts are read back, and the run fails
when they miss the target.

## The file

| Field | Meaning |
|-------|---------|
| `name` | The scenario's name, in the report. |
| `profile` | `light`, `regular`, `heavy`, or `stress`. |
| `duration_seconds`, `ramp_seconds` | How long the run lasts, and how long concurrency takes to climb. |
| `target.p95_ms`, `target.error_ratio` | The pass mark. |
| `weights` | The session's steps by name. Parsed, not applied: the session is fixed. |

## The scenarios

`smoke.yaml`: thirty seconds at `light` on the local stack, p95 500 ms.

```bash
uv run tadas-ops stress --scenario ops/stress/smoke.yaml --orgs 0
```

`staging.yaml`: three minutes at `regular`, p95 3000 ms, dispatched by
`.github/workflows/stress.yml`. A deployed environment signs people in
through a browser, so the run refuses it before it provisions anything.

Both targets are illustrative. A team sets its own.
