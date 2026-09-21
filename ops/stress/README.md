# Stress tests

A stress test is the traffic generator at a higher profile, with a
duration, a ramp, and a target stated before the run. It drives the
edge, the API, the way real clients do, never the managers underneath,
and it reads the signals back when it ends.

## What a good one is

- **The edge is the target.** A run signs in, lists, adds, edits,
  completes, moves, and deletes tasks, reads the diary, and holds one
  socket that sees its own change, then signs out. Every request goes
  through the gateway like a person's would.
- **Sessions are realistic.** Profiles differ by how many orgs and
  members take part, how many run at once, and how long they think
  between requests. `light` is a sanity run; `regular` is a normal day;
  `heavy` is a busy one; `stress` is past that.
- **It ramps.** Concurrency climbs over the ramp, so a knee shows as
  a knee and not as a wall.
- **It soaks.** The duration is long enough for leases to expire,
  sweeps to run, and the cache to fill.
- **The target is stated first.** A p95 and an error ratio, written
  in the scenario before the run. A run without a target is a
  demonstration, not a test.
- **The signals are read back.** After the run, the platform's own
  request counter and its 5xx count are read from its telemetry, and
  the run fails when the platform counted no requests or more errors
  than the target allows. The p95 the verdict holds to the target is
  still the generator's; the platform's p95, the queue, and the worker
  outcomes are not read back yet.

The numbers a system is held to are the team's. The shape is not.

## The scenario file

One YAML file per scenario under this folder.

| Field | Meaning |
|-------|---------|
| `name` | The scenario's name, used in the report. |
| `profile` | `light`, `regular`, `heavy`, or `stress`. |
| `duration_seconds` | How long the run lasts, ramp included. |
| `ramp_seconds` | How long concurrency takes to climb to the profile's. |
| `target.p95_ms` | The p95 latency, in milliseconds, the run must stay under. |
| `target.error_ratio` | The share of requests that may fail, as a fraction. |
| `weights` | The relative weight of each route in a session, by route name. Parsed, not applied yet: the generator's session shape is fixed. |

`smoke.yaml` is the smallest scenario: thirty seconds at the light
profile against the local stack. CI's sanity run is `make traffic`, the
same profile and duration with no target. Locally, `--orgs 0` drives
the seeded org; without it the run provisions tenants through the
operator plane and needs a provisioner configured.

```bash
uv run tadas-ops stress --scenario ops/stress/smoke.yaml --orgs 0
```
