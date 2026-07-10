#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the Ansible project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: bucket_lifecycle
short_description: Manage the lifecycle (ILM) configuration of a RustFS bucket
description:
  - Set or remove the whole lifecycle-rule configuration of a bucket on a
    RustFS server, directly over the S3 API
    (C(PutBucketLifecycleConfiguration) is a full replace - matching the
    server's own semantics, there is no per-rule editing).
  - Comparison is canonical on both sides, rule IDs, empty scoping
    (C(Prefix)/C(Filter)) and date representations can never produce
    false drift.
version_added: "2.0.0"
extends_documentation_fragment:
  - david_igou.rustfs.rustfs
options:
  bucket:
    description:
      - Name of the bucket whose lifecycle configuration is managed.
    type: str
    required: true
  state:
    description:
      - V(present) replaces the bucket's lifecycle configuration with
        O(rules).
      - V(absent) deletes the whole lifecycle configuration.
    type: str
    choices:
      - present
      - absent
    default: present
  rules:
    description:
      - Lifecycle rules in the S3 API shape (C(ID), C(Status), C(Prefix),
        C(Filter), C(Expiration), C(Transitions), ...), as returned by
        C(GetBucketLifecycleConfiguration).
      - Rules without an C(ID) get a deterministic one derived from the
        rule content, so omitting IDs stays idempotent.
      - Required when O(state=present).
      - RustFS 1.0.0-beta.8 honours only a top-level C(Prefix) for scoping;
        a nested C(Filter) prefix surfaces as persistent drift rather than
        being silently masked.
    type: list
    elements: dict
author:
  - David Igou (@david-igou)
"""

EXAMPLES = r"""
- name: Expire objects under tmp/ after 7 days
  david_igou.rustfs.bucket_lifecycle:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
    bucket: backups
    rules:
      - Status: Enabled
        Prefix: tmp/
        Expiration:
          Days: 7

- name: Remove the whole lifecycle configuration
  david_igou.rustfs.bucket_lifecycle:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
    bucket: backups
    state: absent
"""

RETURN = r"""
rules:
  description: Canonicalized lifecycle rules now on the bucket.
  returned: success
  type: list
  elements: dict
  sample:
    - Status: Enabled
      Prefix: tmp/
      Expiration:
        Days: 7
"""

import hashlib
import json

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.common.text.converters import to_native

from ansible_collections.david_igou.rustfs.plugins.module_utils.canonical import (
    canonical_lifecycle_rules,
)
from ansible_collections.david_igou.rustfs.plugins.module_utils.rustfs import (
    RustfsError,
    RustfsNotFoundError,
    rustfs_argument_spec,
    s3_call,
    s3_client,
)


def current_rules(module, client):
    try:
        response = s3_call(
            module.params,
            lambda: client.get_bucket_lifecycle_configuration(Bucket=module.params["bucket"]),
        )
    except RustfsNotFoundError:
        # NoSuchLifecycleConfiguration - no rules configured.
        return []
    return response.get("Rules") or []


def with_rule_ids(rules):
    """Return rules where every rule carries an ID (deterministic when generated)."""
    filled = []
    for rule in rules:
        rule = dict(rule)
        if not rule.get("ID"):
            digest = hashlib.sha256(
                json.dumps(canonical_lifecycle_rules([rule]), sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            rule["ID"] = "ansible-%s" % digest[:16]
        filled.append(rule)
    return filled


def run_module():
    argument_spec = rustfs_argument_spec()
    argument_spec.update(
        bucket=dict(type="str", required=True),
        state=dict(type="str", choices=["present", "absent"], default="present"),
        rules=dict(type="list", elements="dict"),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_if=[("state", "present", ["rules"])],
    )

    bucket = module.params["bucket"]
    state = module.params["state"]
    rules = module.params["rules"]

    result = dict(changed=False)

    try:
        client = s3_client(module)
        existing = current_rules(module, client)
        existing_canonical = canonical_lifecycle_rules(existing)

        if state == "absent":
            result["rules"] = []
            if existing:
                result["changed"] = True
                result["diff"] = dict(before=dict(rules=existing_canonical), after=dict(rules=[]))
                if not module.check_mode:
                    s3_call(module.params, lambda: client.delete_bucket_lifecycle(Bucket=bucket))
            module.exit_json(**result)

        if not rules:
            module.fail_json(
                msg=(
                    "rules must be a non-empty list with state=present - use "
                    "state=absent to remove the whole lifecycle configuration"
                )
            )

        desired_canonical = canonical_lifecycle_rules(rules)
        result["rules"] = desired_canonical

        if existing_canonical != desired_canonical:
            result["changed"] = True
            result["diff"] = dict(
                before=dict(rules=existing_canonical),
                after=dict(rules=desired_canonical),
            )
            if not module.check_mode:
                s3_call(
                    module.params,
                    lambda: client.put_bucket_lifecycle_configuration(
                        Bucket=bucket,
                        LifecycleConfiguration=dict(Rules=with_rule_ids(rules)),
                    ),
                )
    except RustfsError as exc:
        module.fail_json(msg=to_native(exc))

    module.exit_json(**result)


def main():
    run_module()


if __name__ == "__main__":
    main()
