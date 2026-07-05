# RustFS server quirks (empirical, 1.0.0-beta.8 x rc 0.1.24/0.1.25)

Everything below was established by exercising a live `rustfs/rustfs:1.0.0-beta.8`
server with the `rc` CLI — not from documentation. It is the knowledge this
collection's design is built on; re-verify the marked items after every server
or rc pin bump (run your drift job right after any live server upgrade).

## Quirks the role codes around

| Quirk | Consequence in the role |
|---|---|
| `rc mb` / `bucket create` on an EXISTING bucket returns false success | Existence decided by list-first read, never by the create call |
| IAM policy `Action`/`Resource` arrays return in a different order on every call (stored as sets) | `rustfs_canonical_policy` filter on both sides of every comparison |
| `rc ilm rule import` REQUIRES an `id` on every rule; export always emits ids | Spec rules must carry ids; comparison strips them (`rustfs_canonical_ilm`) |
| ILM import is a FULL REPLACE of the bucket's rules | Import is the reconcile primitive — no per-rule editing |
| `rc admin policy rm` while the policy is attached → HTTP 500 | Deletion is out of scope anyway (report-only) |
| No `rc admin policy detach` subcommand exists in 0.1.x | Extra attachments are reported forever, never removed |
| `rc admin user add` on an existing access key rotates the secret in place (attachments survive) | The role NEVER re-adds an existing user; rotation is a manual act |
| `rc alias set` validates credentials against the endpoint (exit 4 on rejection) | Doubles as admin credential validation; liveness catches dead keys at alias registration |
| Admin API (`/rustfs/admin/v3/*`) refuses connections in bursts while the S3 data path stays healthy (observed on live instances) | Every rc call retries, but only on `details.type == "network_error"` in the rc error envelope |
| The rc error envelope marks quota-rejection `retryable: true` | Retry classification keys on `network_error`, NOT on `retryable` |
| `rc bucket remove --force` is unimplemented client-side (exit 6); versioned buckets are undeletable | Deletion safety is absolute: nothing is ever deleted |
| rc release tarball v0.1.25 contains a binary self-reporting 0.1.24 (same surface) | Cosmetic; pin is by tarball version + checksum |
| rc `config.toml` (XDG config) stores alias secrets in plaintext | The role isolates `XDG_CONFIG_HOME` into a run tempdir and shreds it in `always:` |

## Known unknowns (re-verify on every pin bump)

- **ILM id regeneration on import**: so far the server has preserved provided
  rule ids on import. If a future build regenerates them, drift comparison is
  unaffected (ids are stripped), but the unit fixture in
  `tests/unit/plugins/filter/test_rustfs.py` pins the export id key casing
  (lowercase `id`) — an uppercase `ID` would need a deliberate filter change.
- **`ilm rule import` with an empty rule list** (clear-all semantics):
  unverified — the role rejects `rules: []` by assert; omit the `lifecycle`
  key to leave rules unmanaged.
- **Buckets are directories under `/data`** (single-node layout): the molecule
  verify uses `podman exec rustfs-server ls /data` as an independent
  server-side check. This coupling is the FIRST suspect if a server image
  bump breaks verify.
- **`rc ls` / `rc ilm` / `rc version` / `rc quota` are deprecated aliases**
  for `bucket list` / `bucket lifecycle` / `bucket version` / `bucket quota`.
  v1 deliberately ships the alias spellings the validated automation used;
  migrating to canonical verbs is a fixture-gated patch (see README).

## Full empirical matrix (research transcript)

# RustFS 1.0.0-beta.8 server-side reality — empirical feature matrix (rc 0.1.24, throwaway podman servers, 2026-07-04)

Method: fresh `docker.io/rustfs/rustfs:1.0.0-beta.8` containers (one port-mapped, later two host-net instances on :9300/:9301 for cross-server tests), driven by `docker.io/rustfs/rc:latest` (= 0.1.24) with persisted `/root` config. Every verdict below was exercised live, not inferred from --help.

**Headline: `rc:0.1.25` DOES NOT EXIST on Docker Hub (`manifest unknown`). `latest` = 0.1.24. The collection's pin target must stay 0.1.24 until upstream publishes.**

## Feature matrix

| Feature | Verdict | Evidence |
|---|---|---|
| alias set (validates creds) | WORKS | bad creds rejected at alias-set time (ground truth confirmed); good creds "configured successfully" |
| bucket create/list/remove(empty) | WORKS | both `mb` and `bucket create`; JSON output clean |
| bucket remove --force (non-empty) | **BROKEN (client)** | exact error: `--force with object deletion not yet implemented.` Must empty bucket first |
| versioning enable/suspend/info | WORKS | round-trips Enabled/Suspended correctly |
| quota set/info/clear | WORKS (2 quirks) | size is POSITIONAL (`quota set <PATH> <SIZE>`, `--size` rejected); `quota set` response always reports `usage: 0` (cosmetic) but `quota info` reports real usage (10452 B with data present); quotaType always HARD |
| quota ENFORCEMENT | WORKS, opaque client error | server rejects over-quota PUT with HTTP 400 `<Code>InvalidRequest</Code><Message>Bucket quota exceeded. Current usage: 10340 bytes, limit: 20480 bytes</Message>` (verified via raw curl sigv4); **rc surfaces it as `Network error: service error` / `retryable: true`** — a retry loop on uploads would spin forever on quota rejection |
| ILM rule add/list/edit/remove/export | WORKS | add returns generated `rule-xxxxxxxx` id; edit/remove by `--id`; export = list format |
| ILM rule import | WORKS, ids REQUIRED, **REPLACES entire config** | without ids: `Failed to parse lifecycle configuration: missing field 'id'` (confirms ground truth); importing a 2nd file wiped the previous rule — import is full-replace, ideal for declarative reconcile |
| ILM remote tiers (add/list/info/remove) | WORKS | `tier add rustfs COLDX <alias> --endpoint... --bucket... --prefix...` against a 2nd live server succeeded; list/info redact secretKey; positional order is `<TIER_TYPE> <TIER_NAME> <ALIAS>` (info/remove = `<TIER_NAME> <ALIAS>`); ILM rule referencing tier via `--storage-class COLDX` accepted |
| admin user add/list/info/enable/disable/rm | WORKS | disabled user's requests rejected (InvalidRequest); user creds live-verified on data path; AccessDenied on unauthorized bucket → policy enforcement real |
| user secret rotation | WORKS via re-`user add` | re-adding existing user rotates secret in place; old secret → SignatureDoesNotMatch; **policies and group memberships survive rotation** |
| admin policy create/ls/info/rm | WORKS (ordering unstable) | readback scrambles Statement `Action` array order vs input (ground-truth confirmed) — diffing must compare as sets; `policy rm` while attached → HTTP 500 `<Code>InternalError</Code> policy in use` (blocked, but as 500 not a clean 4xx); rm succeeds after user deleted |
| admin policy attach (user/group) | WORKS | `--user` and `--group` both verified |
| admin policy DETACH | **DOES NOT EXIST in rc 0.1.24** | `error: unrecognized subcommand 'detach'` — matches existing role's report-only stance on extra attachments; no CLI path to detach |
| admin group CRUD | WORKS (syntax gotcha) | `group add <ALIAS> <NAME>` takes NO members; members via `group add-members` / `rm-members`; info/enable/disable/rm fine; quirk: group info shows `"policies": [""]` (empty-string element) when none attached; deleting a user auto-removes it from group members |
| service accounts create/ls/info/rm | WORKS (root only) | create takes EXPLICIT access+secret keys (deterministic, IaC-friendly), optional `--policy` file/`--expiry`; parentUser = alias identity; cred live-verified on data path; **plain IAM user CANNOT create service accounts** (AccessDenied) — root/admin-cred only in practice |
| admin access-key info | **BROKEN (server)** | HTTP 500 `<Code>InternalError</Code><Message>get temporary account failed</Message>` on a valid service-account key |
| bucket event add/list/remove | WORKS as config-only | rules persist and round-trip; **server accepts ANY ARN unvalidated** (bogus `arn:aws:sqs:...` accepted) — target existence/delivery is a server-env concern rc cannot manage |
| bucket replication add/list/export | **WORKS end-to-end** (surprise) | cross-server: object uploaded to src appeared in dst within ~6s; requires versioning both sides + alias-qualified `--remote-bucket alias/bucket`; server dials the remote itself → endpoint must be reachable FROM THE SERVER (port-mapped localhost topology fails with ConnectionRefused — molecule design constraint) |
| replication status metrics | PARTIAL | all counters 0 despite successful replication |
| replication remove | PARTIAL | rule removed from config, but command errors `Remote target not found for bucket: src` cleaning up the remote target → nonzero exit on a successful-ish op; idempotency hazard |
| object ops copy/move/remove/stat/find/list | WORKS | all verified incl. cross-bucket move |
| object show / head | WORKS | note `head` prints leading BYTES of content, not metadata (use `stat` for metadata) |
| object share (presign) | WORKS | generated URL fetched 200/10240 via plain curl; default 7d expiry |
| tags (bucket + object) set/list/remove | WORKS | syntax is `-t key=value` (repeatable), NOT positional `k=v&k=v` |
| bucket anonymous set/get | WORKS | arg order is `set <PERMISSION> <PATH>` (permission FIRST); verified 403→200→403 with private/download/private |
| bucket cors set/list/remove | WORKS, camelCase-only | JSON must be `{"rules":[{"allowedOrigins":...,"allowedMethods":...,"allowedHeaders":...,"maxAgeSeconds":...}]}`; snake_case rejected (`missing field allowedOrigins`) |
| sql (S3 Select) | WORKS | `select * from S3Object` on CSV returned rows |
| admin info server/disk, heal status | WORKS | server version string `2026-06-10T07:58:22Z@1.0.0-beta.8`; disk stats sane; heal status returns idle struct |
| admin API stability (local) | STABLE | 20/20 rapid admin calls succeeded → the ~50% connection-level flakiness on the live TrueNAS instances is ENVIRONMENTAL, not inherent to beta.8; keep retries anyway |

## Consequences for the david_igou.rustfs collection

1. Pin rc at **0.1.24** (0.1.25 image unpublished); keep retry wrappers but treat `retryable: true` from rc as unreliable (quota rejection is marked retryable).
2. Reconciliation surface that is fully declarative-safe: buckets, versioning, quota, ILM (import=full-replace with ids), policies (set-compare Actions), users (re-add = rotate), attachments (add-only; report extras — no detach exists), groups, tags, anonymous, CORS (camelCase), events (config-only), tiers.
3. Molecule: replication tests need server-reachable endpoints (shared netns or podman network with server-resolvable names), not host port maps.
4. Known server bugs to code around: `access-key info` 500s; `policy rm` in-use = 500; `replication remove` errors after succeeding; `bucket remove --force` unimplemented (empty bucket first); replication metrics report zeros.

All test containers (scope-rustfs, scope-repl-a, scope-repl-b) removed; rc home dirs deleted. No report files written.\n