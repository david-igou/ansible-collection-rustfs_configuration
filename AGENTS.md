# david_igou.rustfs — agent notes

Ansible collection: declarative in-server state for RustFS via native
modules (direct S3 + admin-API calls from Python; botocore is the single
third-party dependency — no rc CLI anywhere in the collection). Scope is
Layer 1 only (buckets, versioning, ILM, quota, IAM, liveness); server
deployment is out of scope by design.

## Layout

- `plugins/module_utils/rustfs.py` — connection argspec (+ `RUSTFS_*` env
  fallbacks), `RustfsAdminClient` (SigV4-signed JSON for
  `/rustfs/admin/v3/*`), botocore S3 client factory, error taxonomy +
  retry wrapper
- `plugins/module_utils/canonical.py` — canonical policy/ILM comparison
  (single source of truth; the filter plugin delegates here)
- `plugins/modules/rustfs_*.py` — 14 modules (8 state + 6 info), all under
  the `rustfs` action group (meta/runtime.yml)
- `roles/rustfs_state/` — the one role (per-host instance stubs;
  `inventory_hostname` = report prefix). Connection params flow to modules
  via the block-level `environment:` RUSTFS_* fallbacks — NOT
  module_defaults (an action group needs eager collection resolution,
  which breaks ansible-lint's syntax-check; see tasks/main.yml comment)
- `extensions/molecule/default/` — full e2e suite (podman via
  `david_igou.molecule_provisioners`; server container is provisioner-managed,
  the role runs on a connection-local stub). side_effect deliberately still
  uses a pinned rc CLI as an independent drift injector.
- `docs/server-quirks.md` — the empirical beta-8 behavior matrix; read it
  before changing any client call (includes the admin API contract and
  the quirks 2.0.0 overturned)

## Invariants (do not regress)

- Roles are functions: NO secret lookups inside role tasks; credentials
  arrive resolved; `no_log` wherever they flow.
- Deletion safety (ROLE): nothing on the server is ever deleted; unmanaged =
  report (+ opt-in gate). The modules DO expose `state: absent` /
  `exclusive:` — the role must never use them.
- `rustfs_user` never rotates an existing secret without `update_secret`.
- Retries: transport-level failures only (module_utils `retry_call`);
  permanent errors fail fast. Never reintroduce exit-code/string matching.
- Report strings + `set_stats` fact names are stable API (semver-major to
  change).
- Canonicalization lives in module_utils/canonical.py ONLY; filter and
  modules must share it.

## Commands

- Build: `ansible-galaxy collection build`
- Units: `ansible-test units --venv --requirements` (needs botocore →
  tests/unit/requirements.txt; run from an
  `ansible_collections/david_igou/rustfs` checkout)
- Sanity: `ansible-test sanity --venv`
- Lint: `ansible-lint` (offline is OFF on purpose — lint must self-install
  the collection to resolve the FQCN modules; see .config/ansible-lint.yml)
- E2E: `make test` (podman required; MUST run from the collection root)

## Gotchas

- Do NOT point ansible.cfg collections_path at the checkout's own parent
  tree: molecule auto-installs the collection under test with
  `ansible-galaxy collection install --force`, which would resolve the
  install target to the source and DELETE it (this happened once).
- ansible-lint syntax-check eagerly resolves module_defaults groups and
  BARE (argument-less) FQCN module calls — statically-parsed role tasks
  must give every module call at least one argument.
- The 1.0.0-beta.8 server answers some not-founds as HTTP 500
  "does not exist" (canned policies, verified live) — admin `get_*`
  helpers in module_utils normalize this; keep the `_is_not_found` check
  when adding new readers.

## Release

Hand-edit `CHANGELOG.md`, tag. Semver: major = any break to the
`rustfs_state_*` namespace, module interfaces, spec schema, report format,
or stats names.

## Design history

- v1 wrapped the rc CLI from role tasks; 2.0.0 replaced it with native
  modules (spec + design in GitHub issue #3). v1's rc-shaped lifecycle
  spec (lowercase keys) became the standard S3 shape; the canonical ILM
  comparison accepts both.
- Molecule shared literals live in scenario `inventory/group_vars/` rather
  than `files/vars.yml` — inventory scope is required for the provisioner
  to render the server container's env at create time.
