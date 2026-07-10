#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the Ansible project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: group
short_description: Manage IAM groups on a RustFS server
description:
  - Create, remove, enable/disable IAM groups and reconcile their
    membership via the RustFS admin REST API.
version_added: "2.0.0"
extends_documentation_fragment:
  - david_igou.rustfs.rustfs
options:
  name:
    description:
      - Name of the group.
    type: str
    required: true
  state:
    description:
      - Whether the group should exist.
    type: str
    choices:
      - present
      - absent
    default: present
  members:
    description:
      - User access keys that must be members of the group.
      - When omitted, membership is left unmanaged.
    type: list
    elements: str
  append:
    description:
      - When V(true), only add missing members - never remove any.
      - When V(false), make the membership exactly O(members).
    type: bool
    default: false
  status:
    description:
      - Whether the group is enabled or disabled.
      - When omitted, the status is left unmanaged (new groups are created
        enabled by the server).
    type: str
    choices:
      - enabled
      - disabled
author:
  - David Igou (@david-igou)
"""

EXAMPLES = r"""
- name: Create a group with two members
  david_igou.rustfs.group:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
    name: developers
    members:
      - alice
      - bob

- name: Add a member without removing the others
  david_igou.rustfs.group:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
    name: developers
    members:
      - carol
    append: true

- name: Remove the group
  david_igou.rustfs.group:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
    name: developers
    state: absent
"""

RETURN = r"""
group:
  description: Group state after the module ran.
  returned: success
  type: dict
  contains:
    name:
      description: Group name.
      type: str
      sample: developers
    members:
      description: Member access keys.
      type: list
      elements: str
      sample: [alice, bob]
    status:
      description: Group status.
      type: str
      sample: enabled
    policies:
      description: Names of policies attached to the group.
      type: list
      elements: str
      sample: []
"""

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.common.text.converters import to_native

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
        members=dict(type="list", elements="str"),
        append=dict(type="bool", default=False),
        status=dict(type="str", choices=["enabled", "disabled"]),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    name = module.params["name"]
    state = module.params["state"]
    members = module.params["members"]
    append = module.params["append"]
    status = module.params["status"]

    result = dict(changed=False)

    try:
        client = RustfsAdminClient(module)
        existing = client.get_group(name)

        if state == "absent":
            if existing is not None:
                result["changed"] = True
                if not module.check_mode:
                    client.delete_group(name)
            module.exit_json(**result)

        # state == present
        if existing is None:
            result["changed"] = True
            current_members = list(members or [])
            current_status = "enabled"
            if not module.check_mode:
                client.create_group(name, members=members or None)
            current_policies = []
        else:
            current_members = list(existing["members"])
            current_status = existing["status"]
            current_policies = existing["policies"]

            if members is not None:
                to_add = sorted(set(members) - set(current_members))
                to_remove = [] if append else sorted(set(current_members) - set(members))
                if to_add or to_remove:
                    result["changed"] = True
                    result["diff"] = dict(
                        before=dict(members=sorted(current_members)),
                        after=dict(
                            members=sorted(
                                (set(current_members) | set(to_add)) - set(to_remove)
                            )
                        ),
                    )
                    if not module.check_mode:
                        if to_add:
                            client.update_group_members(name, to_add, remove=False)
                        if to_remove:
                            client.update_group_members(name, to_remove, remove=True)
                    current_members = sorted(
                        (set(current_members) | set(to_add)) - set(to_remove)
                    )

        if status is not None and status != current_status:
            result["changed"] = True
            if not module.check_mode:
                client.set_group_status(name, status)
            current_status = status

        result["group"] = dict(
            name=name,
            members=sorted(current_members),
            status=current_status,
            policies=current_policies,
        )
    except RustfsError as exc:
        module.fail_json(msg=to_native(exc))

    module.exit_json(**result)


def main():
    run_module()


if __name__ == "__main__":
    main()
