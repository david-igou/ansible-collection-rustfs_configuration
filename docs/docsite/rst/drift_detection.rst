.. _ansible_collections.david_igou.rustfs.docsite.drift_detection:

Drift detection and reporting
=============================

The :ref:`rustfs_state role <ansible_collections.david_igou.rustfs.docsite.rustfs_state_role>`
is built to run as a **nightly drift job** as well as a converge: the
same play, with ``--check``, becomes a read-only audit that goes red on
any divergence between your spec and the live server.

Check mode is drift detection
-----------------------------

The modules support check mode natively — reads execute, mutations never
do. Under ``--check`` the role therefore computes the full pending change
set without touching the server, and
``rustfs_state_fail_on_drift`` (which defaults to the check-mode flag)
fails the play if that set is non-empty:

.. code-block:: bash

   ansible-playbook site.yml --check          # red on drift
   ansible-playbook site.yml --check --diff   # + canonicalized payload diffs

With ``--diff``, policy and lifecycle drift records carry canonicalized
desired-vs-current payloads (secrets-free) in the end-of-role summary.
If a policy or ILM rule reports a change on *every* run, ``--diff`` is
the first debugging step — it shows the exact field your spec and the
server disagree on.

The report (stable API)
-----------------------

Every run emits three lists, both as facts and via ``set_stats``
(per-host, for automation platforms):

* ``rustfs_state_changes`` — entries like
  ``rustfs-cold:bucket:backups:versioning:enable``,
  ``rustfs-cold:policy:app-rw:update``,
  ``rustfs-cold:user:backup-writer:create``;
* ``rustfs_state_unmanaged_on_server`` — resources present on the server
  but absent from the spec (reported, **never deleted**);
* ``rustfs_state_liveness_failures`` — users whose provided credentials
  no longer authenticate or cannot list their liveness bucket.

Gate order is deliberate: liveness first (a dead credential is the
failure the job status shows), then the opt-in unmanaged gate, then
drift.

Deletion safety and the unmanaged gate
--------------------------------------

The role never deletes anything. Unmanaged resources are reported, and
``rustfs_state_fail_on_unmanaged: true`` escalates the report to a
failure — turning rogue out-of-band resources into a red nightly job.
Individual entries are silenced with
``rustfs_state_ignore_unmanaged`` (shapes: ``bucket:scratch``,
``user:<name>:extra-attachment:<policy>``).

Operators who genuinely want to remove server-side state use the
modules directly — :ansplugin:`david_igou.rustfs.bucket#module`
with ``state: absent``,
:ansplugin:`david_igou.rustfs.policy_attachment#module` with
``exclusive: true`` (the only detach this server has), and so on. The
role's spec never expresses deletion.

Credential liveness
-------------------

For every user with a ``liveness_bucket`` and a ``secret_key``, the role
proves the pair *as stored in your secret store* still works: it must
authenticate against the endpoint and list the given bucket. This
catches out-of-band rotations, stale secret-store items, and wedged
servers — divergence between what your automation believes and what the
server accepts.

The probe (:ansplugin:`david_igou.rustfs.credential_info#module`)
distinguishes *authentication* (the pair is cryptographically valid)
from *authorization* (it may do what was asked); an ``AccessDenied`` is
a verdict, not a retried network blip. Liveness proves authentication
plus listability of one bucket — to audit a credential's full
authorization scope, probe each bucket/verb explicitly.

Estate-scale patterns
---------------------

The spec is plain data, so repetitive per-bucket policies can be
generated from a compact list instead of hand-written:

.. code-block:: yaml

   _rw_buckets: [quay, cnpg-backups, velero, loki-chunks]

   rustfs_state_policies: >-
     {{ _rw_buckets | map('regex_replace', '^(.*)$',
          '{"name": "\1-rw", "document": {"Version": "2012-10-17", "Statement":
           [{"Effect": "Allow",
             "Action": ["s3:GetObject","s3:PutObject","s3:DeleteObject","s3:ListBucket"],
             "Resource": ["arn:aws:s3:::\1","arn:aws:s3:::\1/*"]}]}}')
        | map('from_json') | list }}

At scale the signal is the end-of-role summary;
``ANSIBLE_STDOUT_CALLBACK=yaml`` keeps it readable across dozens of
resources.
