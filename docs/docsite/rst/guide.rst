.. _ansible_collections.david_igou.rustfs.docsite.guide:

Getting started
===============

``david_igou.rustfs`` manages the **in-server state** of
`RustFS <https://rustfs.com>`_ object-storage servers declaratively:
buckets, versioning, lifecycle (ILM) rules, quotas, IAM policies, users,
groups, service accounts, policy attachments, and credential liveness
verification. Everything is done with native modules that speak the two
management planes directly from Python — the S3 API and the RustFS admin
REST API (``/rustfs/admin/v3/*``), both authenticated with AWS SigV4. No
CLI binary is downloaded or shelled out to.

Server deployment and runtime configuration are deliberately out of
scope: this collection reconciles what lives *inside* a running server.

There are two ways to use the collection, and they compose:

* the :ref:`rustfs_state role <ansible_collections.david_igou.rustfs.docsite.rustfs_state_role>`
  — reconcile one whole instance against a declarative per-host spec,
  with drift detection, liveness checks, and deletion safety;
* the modules — direct, single-resource primitives for
  everything else (including the things the role deliberately never
  does, like deleting).

.. note::

   The modules require **botocore** on the Python that executes them.
   For the connection-local host pattern below that means the
   controller/execution environment — botocore is preinstalled in most
   EEs that carry ``amazon.aws``.

The setup
---------

Install the collection — as a git source tracking ``main`` (there is no
Galaxy release or git tag yet):

.. code-block:: yaml

   # requirements.yml
   collections:
     - name: https://github.com/david-igou/ansible-collection-rustfs.git
       type: git
       version: main

.. code-block:: bash

   ansible-galaxy collection install -r requirements.yml

One inventory host per RustFS instance, as a connection-local stub —
the play fans out across instances the way Ansible naturally does:

.. code-block:: yaml

   # inventory
   rustfs_servers:
     hosts:
       rustfs-cold:
         ansible_connection: local

The spec
--------

The whole desired state of an instance lives in that host's
``host_vars``. Credentials arrive **resolved** — the role performs no
secret lookups; lookup expressions belong here, in the caller's data:

.. code-block:: yaml

   # host_vars/rustfs-cold.yml
   rustfs_state_endpoint: https://nas.example.net:20292
   rustfs_state_admin_access_key: "{{ lookup('community.general.onepassword', 'rustfs-cold-admin', field='username', vault='infra') }}"
   rustfs_state_admin_secret_key: "{{ lookup('community.general.onepassword', 'rustfs-cold-admin', field='password', vault='infra') }}"

   # A custom IAM policy. Write the document the natural way — no ID /
   # Sid / Condition boilerplate; the server injects those empties and
   # the canonical comparison absorbs them.
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
     # Versioned bucket: keep the live object, prune OLD VERSIONS after
     # 30 days. Lifecycle rules use the standard S3 API shape
     # (PascalCase); an ID is optional.
     - name: backups
       versioning: true
       lifecycle:
         rules:
           - Status: Enabled
             NoncurrentVersionExpiration:
               NoncurrentDays: 30
     # Non-versioned bucket: expire CURRENT objects 14 days after
     # creation (logs, cluster backups).
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
       secret_key: "{{ lookup('community.general.onepassword', 'backup-writer', field='password', vault='infra') }}"
       liveness_bucket: backups

The playbook is one role include:

.. code-block:: yaml

   - name: Reconcile RustFS instances
     hosts: rustfs_servers
     gather_facts: false
     roles:
       - david_igou.rustfs.rustfs_state

Run it:

.. code-block:: bash

   ansible-playbook site.yml            # converge
   ansible-playbook site.yml --check    # drift detection (fails on drift)
   ansible-playbook site.yml --check --diff   # + exact disagreeing fields

Using the modules directly
--------------------------

Anything the role does not manage — groups, service accounts, quotas,
deletions, exclusive attachments — is available as raw modules. Set the
connection once with the collection's action group:

.. code-block:: yaml

   - hosts: localhost
     gather_facts: false
     module_defaults:
       group/david_igou.rustfs.rustfs:
         endpoint: https://nas.example.net:20292
         access_key: "{{ admin_ak }}"
         secret_key: "{{ admin_sk }}"
     tasks:
       - name: Scoped service account for velero
         david_igou.rustfs.service_account:
           name: svc-velero
           secret: "{{ svc_secret }}"
           policy:
             Version: "2012-10-17"
             Statement:
               - Effect: Allow
                 Action: [s3:PutObject, s3:GetObject, s3:ListBucket]
                 Resource: [arn:aws:s3:::velero, arn:aws:s3:::velero/*]

       - name: Cap the backups bucket at 500 GiB
         david_igou.rustfs.bucket_quota:
           bucket: backups
           size: 500GB

Every connection option can also come from environment variables
(``RUSTFS_ENDPOINT``, ``RUSTFS_ACCESS_KEY``, ``RUSTFS_SECRET_KEY``, …) —
useful with the ``environment`` keyword on a block or play.

The module reference in this docsite documents every module's full
parameter set, return values, and examples — start with
:ansplugin:`david_igou.rustfs.bucket#module`,
:ansplugin:`david_igou.rustfs.policy#module`,
:ansplugin:`david_igou.rustfs.user#module`, and
:ansplugin:`david_igou.rustfs.credential_info#module`.

Migrating from 1.x
------------------

2.0.0 renamed the collection (``david_igou.rustfs_configuration`` →
``david_igou.rustfs``) and removed the ``rc`` CLI dependency. If you are
coming from 1.x:

* update every FQCN (role, filters) to the new collection name;
* drop the ``rustfs_state_rc_*`` pin variables and
  ``rustfs_state_alias`` from your data — they no longer exist;
* rewrite ``lifecycle.rules`` from the rc-export shape (lowercase
  ``id``/``prefix``/``expiration.days``) to the standard S3 API shape
  shown above (``ID`` is now optional);
* install botocore where the modules run.

Everything else — report strings, ``set_stats`` names, gates, the rest
of the ``rustfs_state_*`` spec — is unchanged.
