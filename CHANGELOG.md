# Changelog

## v2.0.0 (unreleased)

Full refactor: native Ansible modules replace the rc CLI wrappers
(spec/design: GitHub issue #3). The modules speak the two management
planes directly from Python — the S3 API through botocore, the RustFS
admin REST API (`/rustfs/admin/v3/*`) with SigV4-signed plain-JSON
requests. No binary is downloaded or shelled out to anywhere.

New content:

- Module and filter names are unprefixed (`david_igou.rustfs.bucket`, not
  `...rustfs_bucket`) - the modern convention for product-named collections
  (microsoft.ad, vmware.vmware, amazon.aws's own de-prefixing): the FQCN
  already carries the product name. Filters renamed accordingly:
  `rustfs_canonical_policy`/`rustfs_canonical_ilm` are now
  `canonical_policy`/`canonical_ilm`. The role stays `rustfs_state` (its
  `rustfs_state_*` variable namespace is stable API).
- Modules (state): `bucket`, `bucket_lifecycle`,
  `bucket_quota`, `policy`, `user`, `group`,
  `service_account`, `policy_attachment` — all with native
  check-mode and `--diff` support, read-first reconcile, canonical
  comparison, and transport-only retries.
- Modules (info): `bucket_info`, `policy_info`,
  `user_info`, `group_info`, `service_account_info`,
  `credential_info` (liveness — distinguishes authentication from
  authorization, which rc's exit codes lumped together).
- `module_utils/rustfs.py` (shared clients, error taxonomy, retry) and
  `module_utils/canonical.py` (single source of canonicalization, shared
  with the filter plugins).
- Action group `david_igou.rustfs.rustfs` for
  `module_defaults`; `RUSTFS_*` environment fallbacks for every
  connection option.
- Groups, service accounts, and quotas are newly manageable (module-level;
  the role's managed surface is unchanged).

Breaking changes (role spec):

- **The collection is renamed `david_igou.rustfs`** (was
  `david_igou.rustfs_configuration`): every FQCN changes —
  `david_igou.rustfs.rustfs_state`, `david_igou.rustfs.bucket`,
  filter `david_igou.rustfs.canonical_policy`, action group
  `group/david_igou.rustfs.rustfs`. Update `requirements.yml` and any
  playbook references; checkouts belong at
  `ansible_collections/david_igou/rustfs`.
- rc pin vars removed: `rustfs_state_rc_version`, `_checksum`, `_arch`,
  `_url`, `_binary`; `rustfs_state_alias` removed (no alias concept, no
  charset asserts).
- `lifecycle.rules` moves from the rc-export JSON shape (lowercase `id`,
  `prefix`, `expiration.days`) to the standard S3 API shape (`ID`
  optional — deterministic IDs are generated — `Prefix`,
  `Expiration.Days`, PascalCase). The `canonical_ilm` filter
  accepts both shapes.
- New runtime dependency **botocore** on the python executing the modules
  (for connection-local stubs: the controller/EE). The rc binary
  download/bake is gone.
- New `rustfs_state_ca_bundle` for private-CA endpoints.

Test suite (from a dedicated meaningfulness audit of units + e2e):

- Per-module unit tests pin the pure decision logic e2e only exercises
  coarsely: the credential probe's authentication-vs-authorization
  verdicts, bucket versioning's unconfigured==suspended tri-state,
  attachment union/exclusive set math, group append-vs-replace membership
  math, user create/rotate/status interplay, and deterministic lifecycle
  rule-ID generation. module_utils additions cover the transport-error →
  retryable mapping, TLS verify/CA plumbing on both planes, retry backoff
  timing, the service-account policy-as-JSON-string serde, and the
  500-as-not-found handling across every admin reader.
- The molecule `default` scenario's spec grew into a small estate (four
  buckets covering all three lifecycle shapes — noncurrent expiry,
  current-object `Expiration.Days`, `Date`-based — with versioning mix,
  three scoped policies, two users), and verify now reads the server back
  through an independent tool (the rc CLI the side-effect phase installs)
  after each drift repair, plus a real authorization round-trip: an
  object PUT with the managed user's credentials, confirmed on the
  server's disk.
- A new molecule `modules` scenario walks the raw-module surface the role
  deliberately never touches: quotas, groups, service accounts (including
  the no-update-endpoint no-op), exclusive attachments (detach), user
  status/secret rotation, bucket deletion (and the versioned-undeletable
  quirk), deleting an attached policy (the 500 detach-first quirk), and
  the authorization-denied credential verdict.

Unchanged (stable API): report strings, `set_stats` names, gate order and
semantics, deletion safety, and the rest of the `rustfs_state_*` spec.

Server behavior discovered/overturned while validating against a live
1.0.0-beta.8 (docs/server-quirks.md has the full matrix):

- A missing canned policy answers HTTP 500 "policy does not exist" (not
  404); admin readers normalize this to not-found.
- `GET /info-canned-policy` wraps the document in
  `{policy_name, policy, create_date, update_date}`; the client unwraps.
- Overturned: the "top-level prefix only" ILM limitation and the
  "rules must carry an id" requirement were rc artifacts — a nested
  `Filter.Prefix` round-trips cleanly over the direct S3 API and id-less
  rules are accepted. `DeleteBucketLifecycle` (clear-all) verified working.

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

Documentation, from a second round of usability testing (four testers each
building the full lab S3 estate — registry, Postgres/Barman backups, RouterOS,
Velero/OADP, AAP, Loki — with least-privilege service accounts):

- Lifecycle: both whole-bucket retention shapes are now shown side by side and
  correctly labelled — `expiration: {days: N}` (expire CURRENT objects, the
  non-versioned logs/backups case, verified to round-trip) and
  `noncurrentVersionExpiration: {noncurrentDays: N}` (expire OLD versions). The
  earlier example was mislabelled a generic "expiration rule" while showing
  only the noncurrent shape; all four testers had to guess the current-object
  key. Anchored by a new filter unit test.
- README gained a "Managing an estate" section: a verified DRY recipe that
  expands a compact bucket list into scoped `<bucket>-rw` policies (the biggest
  ergonomics tax at estate scale), plus notes that liveness proves
  authentication only (verify authorization scope out-of-band with `rc`) and
  that `ANSIBLE_STDOUT_CALLBACK=yaml` keeps output readable across many
  resources.
- Clarified: `access_key` defaults to `name` (set only on mismatch); `--diff`
  covers policy/ILM payloads while versioning drift surfaces in `changes`; the
  union-attach guarantee is stated as one quotable invariant; and an S3
  data-path `AccessDenied` returns rc exit 3 (retryable), not exit 4 — so an
  under-privileged live credential is retried and reported as a liveness
  failure (server-quirks.md).

Retry classification was corrected after reviewing the collection against
the `rustfs/cli` source: the earlier `network_error`-substring predicate
only matched in `--json` output, so it never fired on the write path or
`alias set`; retries now key on rc exit code 3 (the sole retryable code,
emitted identically in human and JSON mode). Verified live against
`1.0.0-beta.8`. See `docs/server-quirks.md`.
