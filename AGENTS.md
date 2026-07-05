# david_igou.rustfs_configuration — agent notes

Ansible collection: declarative in-server state for RustFS via the official
`rc` CLI. Scope is Layer 1 only (buckets, versioning, ILM, IAM, liveness);
server deployment is out of scope by design.

## Layout

- `roles/rustfs_state/` — the one role (per-host instance stubs;
  `inventory_hostname` = report prefix, `rustfs_state_alias` = rc alias)
- `plugins/filter/rustfs.py` — `rustfs_canonical_policy` / `rustfs_canonical_ilm`
- `extensions/molecule/default/` — full e2e suite (podman via
  `david_igou.molecule_provisioners`; server container is provisioner-managed,
  the role runs on a connection-local stub)
- `docs/server-quirks.md` — the empirical beta-8 behavior matrix; read it
  before changing any rc invocation

## Invariants (do not regress)

- Roles are functions: NO secret lookups inside role tasks; credentials
  arrive resolved; `no_log` wherever they flow.
- Deletion safety: nothing on the server is ever deleted; unmanaged =
  report (+ opt-in gate).
- Never re-`rc admin user add` an existing user (rotates its secret).
- Retries only on `network_error`-classified rc failures.
- Report strings + `set_stats` fact names are stable API (semver-major to
  change).
- v1 ships the exact verb spellings the live-validated automation used —
  a deliberate mix: deprecated `rc ls` + `rc ilm rule`, canonical
  `rc bucket create` + `rc bucket version`. Full-canonical migration is a
  fixture-gated patch (docs/server-quirks.md).

## Commands

- Build: `ansible-galaxy collection build`
- Units: `ansible-test units --venv` (from an `ansible_collections/david_igou/rustfs_configuration` checkout)
- Sanity: `ansible-test sanity --venv`
- Lint: `ansible-lint`
- E2E: `make test` (podman required; MUST run from the collection root)

## Gotchas

- Do NOT point ansible.cfg collections_path at the checkout's own parent
  tree: molecule auto-installs the collection under test with
  `ansible-galaxy collection install --force`, which would resolve the
  install target to the source and DELETE it (this happened once).

## Release

Hand-edit `CHANGELOG.md`, tag. Semver: major = any break to the
`rustfs_state_*` namespace, spec schema, report format, or stats names.
rc pin bumps: version + checksum together (Renovate PR has a manual
checksum checklist item).

## Design deviations (accepted, recorded)

Relative to the archived v1 design doc:

- `CHANGELOG.md` hand-edited (design D4) but the creator scaffold's
  antsibull config was dropped rather than never generated.
- `galaxy.yml` uses `license_file: LICENSE` instead of a `license:` list —
  equivalent for Galaxy.
- `extensions/molecule/requirements-test.yml` also pins `containers.podman`
  (the provisioner needs it; harmless extra pin).
- Molecule shared literals live in scenario `inventory/group_vars/` rather
  than `files/vars.yml` — inventory scope is required for the provisioner
  to render the server container's env at create time.
