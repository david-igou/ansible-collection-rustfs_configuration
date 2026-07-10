# david_igou.rustfs

Declarative in-server state management for [RustFS](https://rustfs.com)
object-storage servers, via **native Ansible modules** that speak the two
management planes directly from Python: the S3 API (buckets, versioning,
lifecycle) through botocore, and the RustFS admin REST API
(`/rustfs/admin/v3/*` — users, policies, attachments, groups, service
accounts, quota) with SigV4-signed plain-JSON requests. No CLI binary is
downloaded or shelled out to anywhere.

**Scope: Layer 1 (in-server state) only** — buckets, versioning, lifecycle
(ILM) rules, quota, IAM policies, users, groups, service accounts, policy
attachments, and credential liveness verification, with Ansible check mode
as drift detection. Server deployment and runtime configuration are
deliberately out of scope.

## Contents

| Content | Purpose |
|---|---|
| role `rustfs_state` | Reconcile ONE instance's state against a declarative per-host spec |
| `bucket` / `bucket_info` | Bucket existence + versioning |
| `bucket_lifecycle` | The bucket's whole ILM ruleset (full-replace, canonical comparison) |
| `bucket_quota` | Hard size quota |
| `policy` / `policy_info` | Canned IAM policies (canonical comparison) |
| `user` / `user_info` | IAM users (secret rotation only by explicit opt-in) |
| `group` / `group_info` | IAM groups + membership |
| `service_account` / `service_account_info` | Scoped service accounts |
| `policy_attachment` | Policies attached to a user/group (union or exclusive) |
| `credential_info` | Credential liveness probe (authentication vs authorization) |
| filter `canonical_policy` | Canonical IAM-policy comparison (server ordering is unstable) |
| filter `canonical_ilm` | Canonical ILM-rule comparison (id/scoping/date churn absorbed) |

All modules share one connection interface (`endpoint`, `access_key`,
`secret_key`, TLS/retry options — also injectable via `RUSTFS_*`
environment variables) and are grouped under the
`david_igou.rustfs.rustfs` action group for
`module_defaults`.

## Design invariants

1. **Read-first reconcile** — every module reads, compares canonically,
   and writes only on mismatch; `changed` means a real (or pending) write.
2. **Deletion safety (role)** — server resources absent from the spec are
   reported (`unmanaged_on_server`), optionally gated
   (`rustfs_state_fail_on_unmanaged`), **never deleted**. The modules
   expose `state: absent` / `exclusive:` primitives for operators; the
   role never uses them.
3. **Roles are functions** — no secret lookups inside the role: every
   credential arrives resolved; secret-store lookup expressions belong in
   the caller's data (host_vars). Secrets are `no_log` wherever they flow.
4. **Credential liveness** — the pair *as stored in your secret store* must
   authenticate, proven every run per user with `liveness_bucket`. The
   probe distinguishes authentication from authorization (an
   `AccessDenied` is a verdict, not a retryable network blip).
5. **Check mode = drift detection** — the modules support check mode
   natively: reads execute, mutations do not, the play fails on pending
   changes or dead credentials.
6. **Classified retries** — the beta-8 admin API refuses connections in
   bursts; every API call retries, but only on transport-level failures
   (connection refused/reset, timeouts, HTTP 502/503/504); permanent
   errors fail fast.

See [`docs/server-quirks.md`](docs/server-quirks.md) for the empirical
server-behavior matrix these invariants come from.

## Installing

No Galaxy release or git tag exists yet — consume as a git source tracking
`main`:

```yaml
# requirements.yml
collections:
  - name: https://github.com/david-igou/ansible-collection-rustfs.git
    type: git
    version: main
```

### Requirements

- ansible-core >= 2.16 (`meta/runtime.yml` floor; developed and CI-tested on 2.21)
- **botocore** on the python that executes the modules (for
  connection-local stub hosts: the controller/EE — it is preinstalled in
  most execution environments that carry amazon.aws)
- Network reach from the controller/EE to each instance endpoint

### Local test server

Server deployment is out of scope, but kicking the tires takes one
throwaway container (the exact image the test suite validates against;
no volume, so state vanishes with it):

```console
podman run -d --name rustfs -p 127.0.0.1:9000:9000 \
  -e RUSTFS_ACCESS_KEY=rustfsadmin -e RUSTFS_SECRET_KEY=rustfsadmin123 \
  docker.io/rustfs/rustfs:1.0.0-beta.8 rustfs
```

Then point the spec below at it: `rustfs_state_endpoint: http://127.0.0.1:9000`
with those two values as the admin keys.

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
# lives HERE (data), not in the role. `http://` endpoints are accepted too
# (for a plain-HTTP dev/test instance); rustfs_state_tls_insecure only
# affects TLS endpoints (rustfs_state_ca_bundle for private CAs).
rustfs_state_endpoint: https://nas.example.net:20292
rustfs_state_admin_access_key: "{{ lookup('community.general.onepassword', 'rustfs-cold-admin', field='username', vault='infra') }}"
rustfs_state_admin_secret_key: "{{ lookup('community.general.onepassword', 'rustfs-cold-admin', field='password', vault='infra') }}"

# A custom IAM policy. Write the document the natural way — no ID / Sid /
# Condition boilerplate needed; the server injects those empties and the
# canonical comparison absorbs them, so this converges to steady state.
rustfs_state_policies:
  - name: app-rw
    document:
      Version: "2012-10-17"
      Statement:
        - Effect: Allow
          Action:
            - s3:GetObject
            - s3:PutObject
            - s3:DeleteObject
            - s3:ListBucket
          Resource:
            - arn:aws:s3:::backups
            - arn:aws:s3:::backups/*

rustfs_state_buckets:
  # A versioned bucket: keep the live object, prune OLD VERSIONS after 30
  # days. Rules use the standard S3 API shape (PascalCase — what every S3
  # tool documents); `ID` is optional (deterministic IDs are generated).
  # Scope a rule to a path with a top-level `Prefix: "sub/"`.
  - name: backups
    versioning: true
    lifecycle:
      rules:
        - Status: Enabled
          NoncurrentVersionExpiration:
            NoncurrentDays: 30
  # A non-versioned bucket: expire CURRENT OBJECTS 14 days after creation
  # (the shape a logs / cluster-backup bucket needs — note `Expiration.Days`,
  # distinct from the `NoncurrentVersionExpiration` above).
  - name: logs
    versioning: false
    lifecycle:
      rules:
        - Status: Enabled
          Expiration:
            Days: 14

rustfs_state_users:
  - name: backup-writer
    policies: [app-rw]
    # access_key defaults to `name`; set it only when the stored access key
    # differs from the user name (a mismatch is what liveness catches).
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
- Add `--diff` to get canonicalized desired-vs-current payloads for policy/ILM
  drift (in the end-of-role summary's `diffs` array). **If a policy or ILM
  rule reports a change on *every* run, `--diff` is the first debugging
  step** — it shows the exact field your spec and the server disagree on.

Full interface: [`roles/rustfs_state/README.md`](roles/rustfs_state/README.md)
and `meta/argument_specs.yml` (validated at role start).

### Using the modules directly

Anything the role does not manage (groups, service accounts, quotas,
deletions) is available as raw modules:

```yaml
- name: Scoped service account for velero
  david_igou.rustfs.service_account:
    endpoint: https://nas.example.net:20292
    access_key: "{{ admin_ak }}"
    secret_key: "{{ admin_sk }}"
    name: svc-velero
    secret: "{{ svc_secret }}"
    policy:
      Version: "2012-10-17"
      Statement:
        - Effect: Allow
          Action: [s3:PutObject, s3:GetObject, s3:ListBucket]
          Resource: [arn:aws:s3:::velero, arn:aws:s3:::velero/*]
```

Set connection args once per play with the action group:

```yaml
module_defaults:
  group/david_igou.rustfs.rustfs:
    endpoint: https://nas.example.net:20292
    access_key: "{{ admin_ak }}"
    secret_key: "{{ admin_sk }}"
```

Three things to know when driving the modules directly:

- **Access control is IAM-style, not S3 bucket policies.** There is no
  `PutBucketPolicy` equivalent; grant bucket access with a `policy`
  scoped to the bucket's ARNs and attach it via `policy_attachment`
  (the Quickstart's `app-rw` pattern).
- **The `bucket` module's `versioning` takes `enabled` / `suspended`**
  (the S3 API's state strings) — the booleans in the role spec above are
  a role-level convenience that does not carry over to copied-out module
  tasks.
- **Teardown has server-enforced ordering**: detach a policy from every
  user/group before deleting it, and empty a bucket before
  `state: absent` (with any S3 client — the collection has no
  object-level module). [`docs/server-quirks.md`](docs/server-quirks.md)
  has the full behavior matrix.

## Migrating from 1.x

2.0.0 removes the `rc` CLI dependency entirely. Breaking changes:

| 1.x | 2.0.0 |
|---|---|
| `rustfs_state_rc_version/_checksum/_arch/_url/_binary` | removed (no binary) |
| `rustfs_state_alias` (+ charset asserts) | removed (no alias concept) |
| `lifecycle.rules` in rc-export shape (lowercase `id`, `prefix`, `expiration.days`) | standard S3 API shape (`ID` optional, `Prefix`, `Expiration.Days`, PascalCase) |
| controller needs the rc tarball / a baked binary | controller/EE needs **botocore** |
| `canonical_ilm` filter expects lowercase keys | accepts both shapes |
| — | new: `rustfs_state_ca_bundle` for private CAs |

Report strings, `set_stats` names, gates, and the rest of the
`rustfs_state_*` spec are unchanged.

## Managing an estate

Real deployments have many buckets, each with a service account holding a
read-write policy scoped to just that bucket. The spec is plain data, so you
can generate the repetitive per-bucket policies from a compact list instead of
hand-writing N near-identical blocks. This expands one bucket name into a full
`<bucket>-rw` policy scoped to that bucket (verified to produce the documented
list-of-dicts shape):

```yaml
# host_vars — one line per bucket
_rw_buckets: [quay, cnpg-backups, velero, loki-chunks]

rustfs_state_policies: >-
  {{ _rw_buckets | map('regex_replace', '^(.*)$',
       '{"name": "\1-rw", "document": {"Version": "2012-10-17", "Statement":
        [{"Effect": "Allow",
          "Action": ["s3:GetObject","s3:PutObject","s3:DeleteObject","s3:ListBucket"],
          "Resource": ["arn:aws:s3:::\1","arn:aws:s3:::\1/*"]}]}}')
     | map('from_json') | list }}
```

Keep it as literal blocks if you prefer explicitness; the point is the schema
is ordinary data and loops cleanly — the role only ever sees the resolved
list. Two operational notes:

- **Verify authorization scope, not just liveness.** The role's liveness check
  proves a credential *authenticates* and can list its liveness bucket; it
  does not prove the policy grants every right verb. To audit a service
  account, probe each bucket with `credential_info` (per-bucket
  `bucket_listable`) or exercise the verbs with any S3 client.
- **Readable output at estate scale.** A full converge fans out into many
  tasks; the signal is the end-of-role summary. `ANSIBLE_STDOUT_CALLBACK=yaml`
  (or a `community.general.diff_*` callback) keeps that readable across dozens
  of resources.

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
a connection-local stub host shaped like production. The molecule
side-effect phase still uses a pinned `rc` CLI — deliberately, as an
independent tool injecting drift behind the modules' backs.

### Upgrade checklist (server image bump)

1. Bump the server image pin and the rc pin (side-effect drift injector) in
   `extensions/molecule/default/inventory/group_vars/all.yml`.
2. `make test` must pass — the first suspect on a server-image failure is
   the `/data` server-side check (see docs/server-quirks.md).
3. Re-verify the marked items in docs/server-quirks.md (the 404-vs-500
   not-found shapes and the policy-info envelope are pinned to beta-8).
4. Run your drift job against live instances right after any server upgrade.

Note: RustFS marks ILM 🚧 "under testing" upstream; this collection's ILM
support is nevertheless proven against live instances and in molecule.

## License

GPL-3.0-or-later
