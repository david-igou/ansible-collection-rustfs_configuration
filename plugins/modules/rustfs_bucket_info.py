#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the Ansible project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: rustfs_bucket_info
short_description: Gather information about buckets on a RustFS server
description:
  - List buckets, or report one bucket's existence, versioning state,
    lifecycle rules, and quota.
version_added: "2.0.0"
extends_documentation_fragment:
  - david_igou.rustfs.rustfs
options:
  name:
    description:
      - Name of a single bucket to inspect in detail.
      - When omitted, all buckets are listed (names only).
    type: str
author:
  - David Igou (@david-igou)
"""

EXAMPLES = r"""
- name: List all buckets
  david_igou.rustfs.rustfs_bucket_info:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
  register: all_buckets

- name: Inspect one bucket
  david_igou.rustfs.rustfs_bucket_info:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
    name: backups
  register: backups_bucket
"""

RETURN = r"""
buckets:
  description: Names of all buckets on the server.
  returned: when O(name) is omitted
  type: list
  elements: str
  sample: [backups, scratch]
bucket:
  description: Detail for the requested bucket.
  returned: when O(name) is given
  type: dict
  contains:
    name:
      description: Bucket name.
      type: str
      sample: backups
    exists:
      description: Whether the bucket exists.
      type: bool
      sample: true
    versioning:
      description: Versioning state (V(enabled), V(suspended), or V(unconfigured)).
      type: str
      sample: enabled
    lifecycle_rules:
      description: Lifecycle rules as stored on the server (raw S3 shape).
      type: list
      elements: dict
      sample: []
    lifecycle_rules_canonical:
      description: Lifecycle rules canonicalized for comparison.
      type: list
      elements: dict
      sample: []
    quota:
      description: Hard quota in bytes, V(0) when unlimited.
      type: int
      sample: 0
"""

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.common.text.converters import to_native

from ansible_collections.david_igou.rustfs.plugins.module_utils.canonical import (
    canonical_lifecycle_rules,
)
from ansible_collections.david_igou.rustfs.plugins.module_utils.rustfs import (
    RustfsAdminClient,
    RustfsError,
    RustfsNotFoundError,
    rustfs_argument_spec,
    s3_call,
    s3_client,
)


def bucket_detail(module, client, name):
    detail = dict(name=name)
    try:
        s3_call(module.params, lambda: client.head_bucket(Bucket=name))
    except RustfsNotFoundError:
        detail["exists"] = False
        return detail
    detail["exists"] = True

    versioning = s3_call(module.params, lambda: client.get_bucket_versioning(Bucket=name))
    status = versioning.get("Status")
    detail["versioning"] = status.lower() if status else "unconfigured"

    try:
        lifecycle = s3_call(
            module.params, lambda: client.get_bucket_lifecycle_configuration(Bucket=name)
        )
        rules = lifecycle.get("Rules") or []
    except RustfsNotFoundError:
        rules = []
    detail["lifecycle_rules"] = rules
    detail["lifecycle_rules_canonical"] = canonical_lifecycle_rules(rules)

    quota_info = RustfsAdminClient(module).get_bucket_quota(name) or {}
    detail["quota"] = int(quota_info.get("quota") or 0)
    return detail


def run_module():
    argument_spec = rustfs_argument_spec()
    argument_spec.update(
        name=dict(type="str"),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    name = module.params["name"]
    result = dict(changed=False)

    try:
        client = s3_client(module)
        if name is None:
            response = s3_call(module.params, client.list_buckets)
            result["buckets"] = sorted(
                bucket["Name"] for bucket in response.get("Buckets") or []
            )
        else:
            result["bucket"] = bucket_detail(module, client, name)
    except RustfsError as exc:
        module.fail_json(msg=to_native(exc))

    module.exit_json(**result)


def main():
    run_module()


if __name__ == "__main__":
    main()
