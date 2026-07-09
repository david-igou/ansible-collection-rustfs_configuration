#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the Ansible project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: rustfs_policy
short_description: Manage canned IAM policies on a RustFS server
description:
  - Create, update, or remove canned IAM policies via the RustFS admin
    REST API.
  - Comparison is canonical on both sides. The server echoes stored
    policies back with injected empty boilerplate (an empty document-level
    C(ID) and, per statement, an empty C(Sid) and C(Condition)) and
    reorders C(Action)/C(Resource) arrays on every read - none of that
    produces false drift, so a hand-written document converges to steady
    state.
version_added: "2.0.0"
extends_documentation_fragment:
  - david_igou.rustfs.rustfs
options:
  name:
    description:
      - Name of the canned policy.
    type: str
    required: true
  state:
    description:
      - Whether the policy should exist.
      - Removing a policy that is still attached to a user or group fails
        on the server side (RustFS 1.0.0-beta.8 returns HTTP 500) - detach
        it first with M(david_igou.rustfs.rustfs_policy_attachment).
    type: str
    choices:
      - present
      - absent
    default: present
  document:
    description:
      - The IAM policy document as a dictionary (C(Version), C(Statement)).
      - Required when O(state=present).
    type: dict
author:
  - David Igou (@david-igou)
"""

EXAMPLES = r"""
- name: Create an app read-write policy
  david_igou.rustfs.rustfs_policy:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
    name: app-rw
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

- name: Remove a policy
  david_igou.rustfs.rustfs_policy:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
    name: app-rw
    state: absent
"""

RETURN = r"""
policy:
  description: Policy state after the module ran.
  returned: success
  type: dict
  contains:
    name:
      description: Policy name.
      type: str
      sample: app-rw
    document:
      description: Canonicalized policy document.
      type: dict
      sample:
        Version: "2012-10-17"
        Statement: []
"""

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.common.text.converters import to_native

from ansible_collections.david_igou.rustfs.plugins.module_utils.canonical import (
    canonical_policy,
)
from ansible_collections.david_igou.rustfs.plugins.module_utils.rustfs import (
    RustfsAdminClient,
    RustfsError,
    rustfs_argument_spec,
)


def run_module():
    argument_spec = rustfs_argument_spec()
    argument_spec.update(
        name=dict(type="str", required=True),
        state=dict(type="str", choices=["present", "absent"], default="present"),
        document=dict(type="dict"),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_if=[("state", "present", ["document"])],
    )

    name = module.params["name"]
    state = module.params["state"]
    document = module.params["document"]

    result = dict(changed=False)

    try:
        client = RustfsAdminClient(module)
        existing = client.get_policy(name)
        existing_canonical = canonical_policy(existing) if existing is not None else None

        if state == "absent":
            if existing is not None:
                result["changed"] = True
                if not module.check_mode:
                    try:
                        client.delete_policy(name)
                    except RustfsError as exc:
                        module.fail_json(
                            msg=(
                                "cannot delete policy %s: %s (a policy still attached to a "
                                "user or group cannot be deleted on RustFS 1.0.0-beta.8 - "
                                "detach it first)" % (name, to_native(exc))
                            )
                        )
            module.exit_json(**result)

        desired_canonical = canonical_policy(document)
        result["policy"] = dict(name=name, document=desired_canonical)

        if existing_canonical != desired_canonical:
            result["changed"] = True
            result["diff"] = dict(
                before=dict(document=existing_canonical),
                after=dict(document=desired_canonical),
            )
            if not module.check_mode:
                client.put_policy(name, document)
    except RustfsError as exc:
        module.fail_json(msg=to_native(exc))

    module.exit_json(**result)


def main():
    run_module()


if __name__ == "__main__":
    main()
