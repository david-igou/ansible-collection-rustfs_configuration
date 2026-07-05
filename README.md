# david_igou.rustfs

Declarative in-server state management for [RustFS](https://rustfs.com)
object-storage servers, driven by the official
[`rc` CLI](https://github.com/rustfs/cli) — the only programmable management
surface RustFS ships (the admin REST API is undocumented and pre-stable;
`mc admin` is incompatible with RustFS's admin namespace).

**Scope: Layer 1 (in-server state) only** — buckets, versioning, lifecycle
(ILM) rules, IAM policies, users, policy attachments, and credential
liveness verification, with Ansible check mode as drift detection. Server
deployment and runtime configuration are deliberately out of scope.

## Contents

| Content | Purpose |
|---|---|
| role `david_igou.rustfs.rustfs_state` | Reconcile ONE instance's state against a declarative per-host spec |
| filter `david_igou.rustfs.rustfs_canonical_policy` | Canonical IAM-policy comparison (server ordering is unstable) |
| filter `david_igou.rustfs.rustfs_canonical_ilm` | Canonical ILM-rule comparison (ids server-generated but required on import) |

## Design invariants

1. **Read-first reconcile** — every resource read via `rc … --json`, diffed
   with canonical filters, written only on mismatch.
2. **Deletion safety** — server resources absent from the spec are reported
   (`unmanaged_on_server`), optionally gated (`rustfs_state_fail_on_unmanaged`),
   **never deleted**.
3. **Roles are functions** — no secret lookups inside the role: every
   credential arrives resolved; secret-store lookup expressions belong in
   the caller's data (host_vars). Secrets are `no_log` wherever they flow.
4. **Credential liveness** — the pair *as stored in your secret store* must
   authenticate, proven every run per user with `liveness_bucket`.
5. **Check mode = drift detection** — reads execute, mutations do not, the
   play fails on pending changes or dead credentials.
6. **Classified retries** — the beta-8 admin API refuses connections in
   bursts; every rc call retries, but only on the rc error envelope's
   `network_error` class; permanent errors fail fast.

See [`docs/server-quirks.md`](docs/server-quirks.md) for the empirical
server-behavior matrix these invariants come from.

## Quickstart

One inventory host per RustFS instance, as a connection-local stub:

```yaml
# inventory
rustfs_servers:
  hosts:
    rustfs-cold:
      ansible_connection: local
```

```yaml
# host_vars/rustfs-cold.yml — credentials shown resolved via a lookup that
# lives HERE (data), not in the role
rustfs_state_endpoint: https://nas.example.net:20292
rustfs_state_admin_access_key: "{{ lookup('community.general.onepassword', 'rustfs-cold-admin', field='username', vault='infra') }}"
rustfs_state_admin_secret_key: "{{ lookup('community.general.onepassword', 'rustfs-cold-admin', field='password', vault='infra') }}"

rustfs_state_buckets:
  - name: backups
    versioning: true

rustfs_state_users:
  - name: backup-writer
    policies: [readwrite]
    access_key: "{{ lookup('community.general.onepassword', 'backup-writer', field='username', vault='infra') }}"
    secret_key: "{{ lookup('community.general.onepassword', 'backup-writer', field='password', vault='infra') }}"
    liveness_bucket: backups
```

```yaml
# playbook
- name: Reconcile RustFS instances
  hosts: rustfs_servers
  gather_facts: false
  roles:
    - david_igou.rustfs.rustfs_state
```

- Converge: `ansible-playbook site.yml`
- Drift detection (fails on drift or dead credentials): `ansible-playbook site.yml --check`
- Add `--diff` to get canonicalized desired-vs-current payloads for policy/ILM drift.

Full interface: [`roles/rustfs_state/README.md`](roles/rustfs_state/README.md)
and `meta/argument_specs.yml` (validated at role start).

## Installing

Consume as a git source until a Galaxy release exists:

```yaml
# requirements.yml
collections:
  - name: https://github.com/david-igou/ansible-collection-rustfs.git
    type: git
    version: v1.0.0
```

## Requirements

- ansible-core >= 2.16 (`meta/runtime.yml` floor; developed and CI-tested on 2.21)
- Network reach from the controller/EE to each instance endpoint
- linux-amd64 controller/EE by default — the role downloads a pinned,
  checksum-verified `rc` tarball at runtime. Other arches: set
  `rustfs_state_rc_arch` (+ matching checksum), or bake rc into your EE and
  set `rustfs_state_rc_binary`.

## Development

Molecule needs the repo checked out at a collection path and run from the
collection root (so `extensions/molecule/config.yml` engages):

```console
git clone <repo> ansible_collections/david_igou/rustfs
cd ansible_collections/david_igou/rustfs
make test        # full molecule suite (podman required)
```

Tests use
[`david_igou.molecule_provisioners`](https://github.com/david-igou/ansible-collection-molecule_provisioners)
(podman backend): the RustFS server (`rustfs/rustfs:1.0.0-beta.8`, the exact
version validated live) is a provisioner-managed container; the role runs on
a connection-local stub host shaped like production.

### Upgrade checklist (rc pin or server image bump)

1. Bump `rustfs_state_rc_version` AND `rustfs_state_rc_checksum` together
   (Renovate bumps the version; the checksum is a manual PR step — a stale
   checksum fails safe as a red download).
2. Keep the molecule pin in
   `extensions/molecule/default/inventory/group_vars/all.yml` in step.
3. `make test` must pass — the first suspect on a server-image failure is
   the `/data` server-side check (see docs/server-quirks.md).
4. Run your drift job against live instances right after any server upgrade.

Note: RustFS marks ILM 🚧 "under testing" upstream; this collection's ILM
support is nevertheless proven against live instances and in molecule.

## License

GPL-3.0-or-later
