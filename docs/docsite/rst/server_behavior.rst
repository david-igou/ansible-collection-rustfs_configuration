.. _ansible_collections.david_igou.rustfs.docsite.server_behavior:

Server behavior, errors, and retries
====================================

RustFS (validated against ``1.0.0-beta.8``) has empirically-established
behaviors the modules code around so that *you* never have to. This page
summarizes the operationally relevant ones; the full behavior matrix
lives in the repository at
`docs/server-quirks.md <https://github.com/david-igou/ansible-collection-rustfs_configuration/blob/main/docs/server-quirks.md>`_.

The two management planes
-------------------------

* **S3 data plane** — buckets, versioning, lifecycle. Stock S3 API
  calls, driven through botocore with path-style addressing.
* **Admin REST API** — ``/rustfs/admin/v3/*`` for users, canned
  policies, attachments, groups, service accounts, quota. Plain-JSON
  bodies (camelCase keys), authenticated with AWS SigV4 exactly like the
  S3 plane.

Both planes accept the same credential pair; every module takes one
``endpoint`` / ``access_key`` / ``secret_key`` set (or the ``RUSTFS_*``
environment variables).

Error classification and retries
--------------------------------

The beta-8 admin API is known to refuse connections in bursts while the
S3 data path stays healthy. Every module call therefore retries — but
**only transport-level failures**: connection refused/reset, timeouts,
and HTTP 502/503/504. Everything else is permanent and fails
immediately with a clear message:

* authentication/authorization errors (HTTP 401/403,
  ``SignatureDoesNotMatch``, ``InvalidAccessKeyId``, ``AccessDenied``);
* not-found (HTTP 404 — and the beta-8 special case below);
* conflicts (HTTP 409) and validation errors.

Tune the budget with ``retries`` (total attempts, default 8) and
``retry_delay`` (seconds, default 3) on any module.

Canonical comparison
--------------------

The server does not echo state back the way you wrote it. The modules
compare canonically on both sides so none of this produces false drift:

* IAM policy ``Action``/``Resource`` arrays return in a different order
  on every read (stored as sets), and the echo injects empty
  boilerplate (a document-level ``ID`` and per-statement ``Sid`` /
  ``Condition`` empties) — write your documents the natural way;
* lifecycle rule IDs are comparison-irrelevant (rules without an ``ID``
  get a deterministic generated one);
* empty lifecycle scoping (``Prefix: ""``) is dropped by the server on
  read — a whole-bucket rule stays idempotent either way;
* lifecycle ``Date`` fields compare equal across representations
  (``2026-01-01`` in your spec vs. the datetime the server returns).

The same canonicalization is exposed as the
``david_igou.rustfs.rustfs_canonical_policy`` and
``david_igou.rustfs.rustfs_canonical_ilm`` filters.

Behaviors worth knowing when using the modules directly
-------------------------------------------------------

* **Policy attachment is a full replace.** The server's only attachment
  primitive replaces the whole set, and there is no detach endpoint.
  :ansplugin:`david_igou.rustfs.rustfs_policy_attachment#module`
  defaults to the safe union (nothing is ever detached); pass
  ``exclusive: true`` to make the set exactly what you list — which is
  how detaching works on this server.
* **Re-adding a user rotates its secret in place.**
  :ansplugin:`david_igou.rustfs.rustfs_user#module` therefore never
  re-sends an existing user's secret unless you opt in with
  ``update_secret: true``.
* **A policy still attached to a user or group cannot be deleted**
  (the server answers HTTP 500) — detach first, then remove.
* **Versioned buckets are undeletable** on beta-8;
  ``rustfs_bucket`` with ``state: absent`` surfaces that as a clear
  error instead of a generic failure.
* **Missing canned policies answer HTTP 500** ("policy does not
  exist"), not 404 — the modules normalize this to not-found, so a
  first converge on a fresh server is clean and fast.
* **Service accounts cannot be updated** (no endpoint exists) — to
  change a policy or expiration, remove and recreate the account.
* **Lifecycle configuration is replaced whole.** There is no per-rule
  editing anywhere in the stack;
  :ansplugin:`david_igou.rustfs.rustfs_bucket_lifecycle#module` treats
  your ``rules`` list as the entire configuration, and
  ``state: absent`` removes the whole configuration.

Scope lifecycle rules with a top-level ``Prefix``. A nested
``Filter.Prefix`` round-trips cleanly over the direct S3 API, but
whether the expiry scanner honours it at execution time is unverified on
beta-8 — top-level ``Prefix`` is the proven shape.
