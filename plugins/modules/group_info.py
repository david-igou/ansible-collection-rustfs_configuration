#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the Ansible project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: group_info
short_description: Gather information about IAM groups on a RustFS server
description:
  - List IAM groups, or report one group's members, status, and attached
    policies.
version_added: "2.0.0"
extends_documentation_fragment:
  - david_igou.rustfs.rustfs
options:
  name:
    description:
      - Name of a single group to inspect.
      - When omitted, all group names are listed.
    type: str
author:
  - David Igou (@david-igou)
"""

EXAMPLES = r"""
- name: List all groups
  david_igou.rustfs.group_info:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
  register: all_groups

- name: Inspect one group
  david_igou.rustfs.group_info:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
    name: developers
  register: developers
"""

RETURN = r"""
groups:
  description: Names of all groups on the server.
  returned: when O(name) is omitted
  type: list
  elements: str
  sample: [developers]
group:
  description: Detail for the requested group.
  returned: when O(name) is given
  type: dict
  contains:
    name:
      description: Group name.
      type: str
      sample: developers
    exists:
      description: Whether the group exists.
      type: bool
      sample: true
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
        name=dict(type="str"),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    name = module.params["name"]
    result = dict(changed=False)

    try:
        client = RustfsAdminClient(module)
        if name is None:
            result["groups"] = sorted(client.list_groups())
        else:
            info = client.get_group(name)
            group = dict(name=name, exists=info is not None)
            if info is not None:
                group.update(info)
            result["group"] = group
    except RustfsError as exc:
        module.fail_json(msg=to_native(exc))

    module.exit_json(**result)


def main():
    run_module()


if __name__ == "__main__":
    main()
