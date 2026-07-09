#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the Ansible project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: rustfs_user_info
short_description: Gather information about IAM users on a RustFS server
description:
  - List IAM users, or report one user's status, attached policies, and
    group memberships.
  - Secrets are never returned (the server does not expose them).
version_added: "2.0.0"
extends_documentation_fragment:
  - david_igou.rustfs_configuration.rustfs
options:
  name:
    description:
      - Access key of a single user to inspect.
      - When omitted, all users are listed.
    type: str
author:
  - David Igou (@david-igou)
"""

EXAMPLES = r"""
- name: List all users
  david_igou.rustfs_configuration.rustfs_user_info:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
  register: all_users

- name: Inspect one user
  david_igou.rustfs_configuration.rustfs_user_info:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
    name: app-backups
  register: app_user
"""

RETURN = r"""
users:
  description: All users on the server.
  returned: when O(name) is omitted
  type: list
  elements: dict
  sample:
    - name: app-backups
      status: enabled
      policies: [app-rw]
      member_of: []
user:
  description: Detail for the requested user.
  returned: when O(name) is given
  type: dict
  contains:
    name:
      description: The user's access key.
      type: str
      sample: app-backups
    exists:
      description: Whether the user exists.
      type: bool
      sample: true
    status:
      description: Account status.
      type: str
      sample: enabled
    policies:
      description: Names of policies attached to the user.
      type: list
      elements: str
      sample: [app-rw]
    member_of:
      description: Groups the user belongs to.
      type: list
      elements: str
      sample: []
"""

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.common.text.converters import to_native

from ansible_collections.david_igou.rustfs_configuration.plugins.module_utils.rustfs import (
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
            users = client.list_users()
            result["users"] = [
                dict(name=access_key, **info)
                for access_key, info in sorted(users.items())
            ]
        else:
            info = client.get_user(name)
            user = dict(name=name, exists=info is not None)
            if info is not None:
                user.update(info)
            result["user"] = user
    except RustfsError as exc:
        module.fail_json(msg=to_native(exc))

    module.exit_json(**result)


def main():
    run_module()


if __name__ == "__main__":
    main()
