# rustfs_state

Reconcile ONE RustFS instance's in-server state — IAM policies, buckets,
versioning, lifecycle (ILM) rules, users, policy attachments — against a
declarative per-host spec, verify that the provided credentials actually
authenticate, and (in check mode) fail on any drift.

## One host = one instance

The role reconciles **the inventory host it runs on**: a connection-local
stub named after the instance. `inventory_hostname` prefixes every report
entry; `rustfs_state_alias` (default: the hostname) is the rc alias. The
play fans out across instances the way Ansible naturally does — there is
no instances list.

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
| `rustfs_state_alias` | `inventory_hostname` | rc alias (charset-asserted: `^[a-z0-9][a-z0-9-]*$`) |
| `rustfs_state_tls_insecure` | `false` | Allow insecure TLS on alias registrations |
| `rustfs_state_rc_version` / `_checksum` / `_arch` / `_url` | pinned | rc toolchain pin (bump version+checksum together) |
| `rustfs_state_rc_binary` | `""` | Pre-installed rc path (skips download) |
| `rustfs_state_retries` / `rustfs_state_retry_delay` | `8` / `3` | Retry policy (network-classified errors only) |
| `rustfs_state_builtin_policies` | server builtins | Never reported as unmanaged |
| `rustfs_state_fail_on_drift` | `ansible_check_mode` | Fail on (pending) changes — the drift-job mechanism |
| `rustfs_state_fail_on_unmanaged` | `false` | Escalate unmanaged resources to a failure |
| `rustfs_state_ignore_unmanaged` | `[]` | `<kind>:<name>` allowlist for the unmanaged report/gate |

Spec details (verbatim exports, ILM id requirement, liveness semantics) are
documented in `meta/argument_specs.yml` and the collection README.

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
  desired-vs-current payloads (secrets-free) in the summary.

## Behavioral invariants

1. Read-first reconcile; canonical comparison via the collection filters.
2. Deletion safety: unmanaged resources are reported (optionally gated),
   never deleted; extra attachments report-only (no detach in rc 0.1.x).
3. Secrets: never looked up, never generated, never rewritten for an
   existing user (re-`user add` would rotate the secret); `no_log`
   everywhere secrets flow (including `user add`, which echoes the secret).
4. Liveness: per user with `liveness_bucket` + `secret_key`, the provided
   pair lists the bucket; all failures are collected, the full report is
   emitted, then the play fails. Check mode skips users pending creation.
   Gate order: liveness, then unmanaged (opt-in), then drift.
5. Check-mode correctness: reads run under `--check`; mutations never do.
6. Classified retries: `network_error` retries, everything else fails
   fast; rejected admin credentials (`alias set` exit 4) fail immediately
   with a clear, secret-free message.
7. rc hygiene: tempdir-isolated `XDG_CONFIG_HOME` (rc stores alias secrets
   in plaintext), shredded in `always:`.

Server quirks these come from: `../../docs/server-quirks.md`.
