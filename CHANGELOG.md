# Changelog

## v1.0.0 (unreleased)

Initial release.

- Role `rustfs_state`: declarative in-server state for one RustFS instance
  (IAM policies, buckets, versioning, ILM rules, users, attachments) via
  the pinned, checksum-verified `rc` CLI; credential liveness verification;
  check mode as drift detection; deletion safety (report-only unmanaged
  resources, opt-in `fail_on_unmanaged` gate with allowlist); retries keyed
  on rc exit code 3 (NetworkError) for the beta-8 admin API's bursts; a
  fail-fast guard requiring an `id` on every managed lifecycle rule;
  per-host `set_stats` export; `--diff` payloads for policy/ILM drift.
- Filters `rustfs_canonical_policy` / `rustfs_canonical_ilm`: canonical
  comparison absorbing unstable server-side ordering and ILM id churn.
- Molecule suite (podman via `david_igou.molecule_provisioners`): converge
  from empty, idempotence, out-of-band drift injection and exact-change-set
  repair with independent server-side verification, drift (check) mode,
  versioning suspend, unmanaged report/escalate/allowlist, dead-credential
  liveness failure, and retry classification (exit-4 fast-fail, exit-3
  retried).

Idempotence fixes (found by fresh-user usability testing against a live
`1.0.0-beta.8` server, then reproduced directly):

- `rustfs_canonical_policy` now drops the empty `Sid: ""` the server injects
  into every stored statement (it already dropped empty `ID`/`Condition`). A
  hand-authored policy document written without `Sid` no longer re-applies
  `policy:<name>:update` on every run. The molecule fixture masked this by
  giving every statement a non-empty `Sid`.
- `rustfs_canonical_ilm` now treats empty scoping (`prefix: ""` or an empty
  `filter`) as absent, matching the server's export which drops it — a
  whole-bucket lifecycle rule written with an explicit empty prefix/filter no
  longer re-imports on every run. New docs make clear that path-scoping must
  use a top-level `prefix:` (the server ignores a nested `filter:`).
- Bucket `versioning: null` (bare key) is now treated as "unmanaged", the same
  as omitting it — silencing a `None -> bool` deprecation warning (an error on
  ansible-core 2.23).

Documentation: the README Quickstart now shows a complete worked example
(custom IAM policy + versioned bucket with a lifecycle rule + user); the policy
`document` and `lifecycle.rules` shapes are documented with minimal examples in
`meta/argument_specs.yml`; `http://` endpoints and the TLS-only scope of
`rustfs_state_tls_insecure` are stated explicitly; the dead-credential message
now includes a troubleshooting hint; and `docs/server-quirks.md` records the
policy-boilerplate and ILM-scoping server behaviours above.

Retry classification was corrected after reviewing the collection against
the `rustfs/cli` source: the earlier `network_error`-substring predicate
only matched in `--json` output, so it never fired on the write path or
`alias set`; retries now key on rc exit code 3 (the sole retryable code,
emitted identically in human and JSON mode). Verified live against
`1.0.0-beta.8`. See `docs/server-quirks.md`.
