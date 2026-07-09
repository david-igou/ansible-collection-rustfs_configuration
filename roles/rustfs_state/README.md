# rustfs_state

Reconcile ONE RustFS instance's in-server state — IAM policies, buckets,
versioning, lifecycle (ILM) rules, users, policy attachments — against a
declarative per-host spec, verify that the provided credentials actually
authenticate, and (in check mode) fail on any drift.

All server access goes through this collection's `rustfs_*` modules
(direct S3 + admin-API calls from Python) — no CLI binary, no alias
store, no tempdir scaffolding.

## One host = one instance

The role reconciles **the inventory host it runs on**: a connection-local
stub named after the instance. `inventory_hostname` prefixes every report
entry. The play fans out across instances the way Ansible naturally does —
there is no instances list.

## The role is a function

Pure over its inputs, validated at start by `meta/argument_specs.yml`.
Every credential arrives as a resolved value (`no_log` fields); the role
performs no secret lookups — lookup expressions live in the caller's
host_vars, where they are just values of this schema.

## Interface

| Variable | Default | Purpose |
|---|---|---|
| `rustfs_state_endpoint` | — (required) | Instance base URL |
| `rustfs_state_admin_access_key` | — (required) | Resolved admin access key |
| `rustfs_state_admin_secret_key` | — (required) | Resolved admin secret key |
| `rustfs_state_policies` | `[]` | Managed IAM policies (`{name, document}`) |
| `rustfs_state_buckets` | `[]` | Managed buckets (`{name, versioning?, lifecycle?}`) |
| `rustfs_state_users` | `[]` | Managed users (`{name, policies, secret_key?, access_key?, liveness_bucket?}`) |
| `rustfs_state_tls_insecure` | `false` | Allow insecure TLS (TLS-only; no-op for `http://`) |
| `rustfs_state_ca_bundle` | `""` | CA bundle path for private-CA endpoints |
| `rustfs_state_retries` / `rustfs_state_retry_delay` | `8` / `3` | Retry policy (transport-level failures only) |
| `rustfs_state_builtin_policies` | server builtins | Never reported as unmanaged |
| `rustfs_state_fail_on_drift` | `ansible_check_mode` | Fail on (pending) changes — the drift-job mechanism |
| `rustfs_state_fail_on_unmanaged` | `false` | Escalate unmanaged resources to a failure |
| `rustfs_state_ignore_unmanaged` | `[]` | `<kind>:<name>` allowlist for the unmanaged report/gate |

Spec details — worked `document` / `lifecycle.rules` examples and liveness
semantics — are in `meta/argument_specs.yml` and the collection README
Quickstart. Three shapes worth calling out up front:

- **Policy `document`**: write it plainly (`Version` + `Statement` list); no
  `ID`/`Sid`/`Condition` boilerplate needed — the server adds those empties and
  the canonical comparison absorbs them, so a from-scratch policy stays
  idempotent.
- **`lifecycle.rules`**: the rules **array only**, in the standard S3 API
  shape (PascalCase — what every S3 tool documents). An `ID` is optional
  (deterministic IDs are generated). Two whole-bucket retention shapes:
  `Expiration: {Days: N}` expires **current objects** (non-versioned buckets —
  logs, cluster backups), `NoncurrentVersionExpiration: {NoncurrentDays: N}`
  expires **old versions** (versioned buckets). Scope with a top-level
  `Prefix:`, not a nested `Filter:` (the server keeps only top-level prefix). If
  a policy or ILM rule shows a change on *every* run, re-run with `--diff` — it
  prints the exact disagreeing field.
- **`access_key`** (per user): defaults to the user's `name`; set it only when
  the stored access key differs from the name. A mismatch between it and the
  identity the secret actually authenticates as is exactly what liveness
  catches — liveness proves *authentication* plus listability of the one
  liveness bucket, not full authorization scope (to audit the latter, probe
  the account's creds against each verb with any S3 client, or use the
  `rustfs_credential_info` module per bucket).

## Outputs (stable API)

- Report strings `<inventory_hostname>:<kind>:<name>[:<action>]` in the
  facts `rustfs_state_changes`, `rustfs_state_unmanaged`,
  `rustfs_state_liveness_failures` (also printed as the end-of-role
  summary).
- The same three lists exported via `set_stats` (per-host) for automation
  platforms and notification pipelines, under the stat names
  `rustfs_state_changes`, `rustfs_state_unmanaged_on_server` (note: NOT the
  fact's shorter name), and `rustfs_state_liveness_failures`.
- With `--diff`, policy/ILM change records carry canonicalized
  desired-vs-current payloads (secrets-free) in the summary. Scope: `diffs`
  covers policy and ILM only; a versioning change surfaces in `changes`
  (e.g. `…:bucket:<name>:versioning:enable`), not `diffs` — the two-state
  current-vs-desired is implicit in the action.

## Behavioral invariants

1. Read-first reconcile; canonical comparison inside the modules (shared
   with the collection filters via module_utils).
2. Deletion safety: unmanaged resources are reported (optionally gated),
   never deleted; extra attachments report-only (the role never uses the
   attachment module's `exclusive` mode). Policy attach is a full REPLACE
   server-side, so the attachment module always sends
   `union(existing, desired)` — desired policies converge, out-of-band
   extras survive and stay visible as `extra-attachment` reports.
3. Secrets: never looked up, never generated, never rewritten for an
   existing user (the `rustfs_user` module rotates only with an explicit
   `update_secret` opt-in, which the role never sets); `no_log` everywhere
   secrets flow.
4. Liveness: per user with `liveness_bucket` + `secret_key`, the provided
   pair authenticates and lists the bucket (`rustfs_credential_info`); all
   failures are collected, the full report is emitted, then the play
   fails. Check mode skips users pending creation. Gate order: liveness,
   then unmanaged (opt-in), then drift.
5. Check-mode correctness: the modules support check mode natively — reads
   run under `--check`; mutations never do.
6. Classified retries: transport-level failures (connection refused/reset,
   timeouts, HTTP 502/503/504) retry, everything else fails fast; rejected
   admin credentials fail immediately with a clear, secret-free message.
   Unlike the old rc CLI path, a data-path `AccessDenied` is now a proper
   auth verdict, not a retried "network error".

Server quirks these come from: `../../docs/server-quirks.md`.
