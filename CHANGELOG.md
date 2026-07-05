# Changelog

## v1.0.0 (unreleased)

Initial release.

- Role `rustfs_state`: declarative in-server state for one RustFS instance
  (IAM policies, buckets, versioning, ILM rules, users, attachments) via
  the pinned, checksum-verified `rc` CLI; credential liveness verification;
  check mode as drift detection; deletion safety (report-only unmanaged
  resources, opt-in `fail_on_unmanaged` gate with allowlist); classified
  retries for the beta-8 admin API's connection-refusal bursts; per-host
  `set_stats` export; `--diff` payloads for policy/ILM drift.
- Filters `rustfs_canonical_policy` / `rustfs_canonical_ilm`: canonical
  comparison absorbing unstable server-side ordering and ILM id churn.
- Molecule suite (podman via `david_igou.molecule_provisioners`): converge
  from empty, idempotence, out-of-band drift injection and exact-change-set
  repair with independent server-side verification, drift (check) mode,
  versioning suspend, unmanaged report/escalate/allowlist, dead-credential
  liveness failure.
