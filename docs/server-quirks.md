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
| `rc admin policy attach` REPLACES the user's whole policy set (not additive — attaching B to a user holding A leaves only B) | The role attaches the UNION of current + desired, so extras survive and desired policies converge instead of oscillating |
| No `rc admin policy detach` subcommand exists in 0.1.x | Extra attachments are reported, never removed by the role; an operator CAN remediate manually by replace-attaching the desired-only set, or allowlist via `rustfs_state_ignore_unmanaged` |
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
- **Verb spellings shipped in v1** (exactly what the live-validated
  automation used, mixed by design): deprecated aliases `rc ls` (bucket
  enumeration + liveness object listing) and `rc ilm rule export/import`;
  canonical `rc bucket create` and `rc bucket version info/enable/suspend`;
  `rc admin ...` (only form). Unifying on canonical verbs (`bucket list`,
  `bucket lifecycle rule`, `object list`) is a fixture-gated patch — pin
  per-command JSON output first, then migrate, then re-verify live no-op.
