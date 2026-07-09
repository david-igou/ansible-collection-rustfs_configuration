#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the Ansible project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: rustfs_bucket_quota
short_description: Manage the hard quota of a RustFS bucket
description:
  - Set or clear a bucket's hard size quota via the RustFS admin REST API
    (C(/rustfs/admin/v3/quota/{bucket})).
  - RustFS currently supports only hard quotas.
version_added: "2.0.0"
extends_documentation_fragment:
  - david_igou.rustfs.rustfs
options:
  bucket:
    description:
      - Name of the bucket.
    type: str
    required: true
  state:
    description:
      - V(present) sets the quota to O(size), V(absent) clears it.
    type: str
    choices:
      - present
      - absent
    default: present
  size:
    description:
      - Quota limit. Either a byte count or a human-readable size such as
        V(10GB) or V(512MB).
      - Required when O(state=present).
    type: str
author:
  - David Igou (@david-igou)
"""

EXAMPLES = r"""
- name: Cap the backups bucket at 500 GiB
  david_igou.rustfs.rustfs_bucket_quota:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
    bucket: backups
    size: 500GB

- name: Remove the quota
  david_igou.rustfs.rustfs_bucket_quota:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
    bucket: backups
    state: absent
"""

RETURN = r"""
quota:
  description: Quota state after the module ran.
  returned: success
  type: dict
  contains:
    bucket:
      description: Bucket name.
      type: str
      sample: backups
    quota:
      description: Quota limit in bytes, V(0) when unlimited.
      type: int
      sample: 536870912000
    size:
      description: Current bucket usage in bytes, as reported by the server.
      type: int
      sample: 1024
"""

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.common.text.converters import to_native
from ansible.module_utils.common.text.formatters import human_to_bytes

from ansible_collections.david_igou.rustfs.plugins.module_utils.rustfs import (
    RustfsAdminClient,
    RustfsError,
    rustfs_argument_spec,
)


def run_module():
    argument_spec = rustfs_argument_spec()
    argument_spec.update(
        bucket=dict(type="str", required=True),
        state=dict(type="str", choices=["present", "absent"], default="present"),
        size=dict(type="str"),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_if=[("state", "present", ["size"])],
    )

    bucket = module.params["bucket"]
    state = module.params["state"]

    desired = 0
    if state == "present":
        try:
            desired = int(human_to_bytes(module.params["size"]))
        except ValueError as exc:
            module.fail_json(msg="cannot parse size %r: %s" % (module.params["size"], to_native(exc)))
        if desired <= 0:
            module.fail_json(msg="size must be positive - use state=absent to clear the quota")

    result = dict(changed=False)

    try:
        client = RustfsAdminClient(module)
        info = client.get_bucket_quota(bucket) or {}
        current = int(info.get("quota") or 0)

        if current != desired:
            result["changed"] = True
            result["diff"] = dict(before=dict(quota=current), after=dict(quota=desired))
            if not module.check_mode:
                if state == "present":
                    client.set_bucket_quota(bucket, desired)
                else:
                    client.clear_bucket_quota(bucket)

        result["quota"] = dict(
            bucket=bucket,
            quota=desired if result["changed"] else current,
            size=int(info.get("size") or 0),
        )
    except RustfsError as exc:
        module.fail_json(msg=to_native(exc))

    module.exit_json(**result)


def main():
    run_module()


if __name__ == "__main__":
    main()
