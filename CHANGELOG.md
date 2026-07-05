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

Retry classification was corrected after reviewing the collection against
the `rustfs/cli` source: the earlier `network_error`-substring predicate
only matched in `--json` output, so it never fired on the write path or
`alias set`; retries now key on rc exit code 3 (the sole retryable code,
emitted identically in human and JSON mode). Verified live against
`1.0.0-beta.8`. See `docs/server-quirks.md`.
