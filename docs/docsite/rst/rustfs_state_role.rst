.. _ansible_collections.david_igou.rustfs.docsite.rustfs_state_role:

david_igou.rustfs.rustfs_state role
===================================

Reconciles ONE RustFS instance's in-server state — IAM policies, buckets,
versioning, lifecycle rules, users, and policy attachments — against a
declarative per-host spec, verifies that the provided credentials
actually authenticate, and (in check mode) fails on any drift.

The role reconciles the inventory host it runs on: a connection-local
stub named after the instance, so a play fans out across instances the
way Ansible naturally does. It is a pure function over its inputs —
credentials arrive resolved, nothing is looked up, nothing on the server
is ever deleted.

See the :ansplugin:`full role reference <david_igou.rustfs.rustfs_state#role>`
for all parameters and defaults, the
:ref:`getting-started guide <ansible_collections.david_igou.rustfs.docsite.guide>`
for a worked spec, and
:ref:`drift detection <ansible_collections.david_igou.rustfs.docsite.drift_detection>`
for the reporting contract and nightly-audit pattern.
