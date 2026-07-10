#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the Ansible project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: user
short_description: Manage IAM users on a RustFS server
description:
  - Create, remove, enable/disable IAM users via the RustFS admin REST API.
  - An existing user's secret is B(never) touched unless O(update_secret=true) -
    on RustFS, re-adding an existing access key rotates its secret in place,
    so rotation is a deliberate act, not a converge side effect.
  - The module never generates credentials, the secret arrives resolved from
    the caller.
version_added: "2.0.0"
extends_documentation_fragment:
  - david_igou.rustfs.rustfs
options:
  name:
    description:
      - The user's access key (RustFS identifies users by access key).
    type: str
    required: true
  state:
    description:
      - Whether the user should exist.
    type: str
    choices:
      - present
      - absent
    default: present
  secret:
    description:
      - The user's secret key.
      - Required to create a user, ignored for an existing user unless
        O(update_secret=true).
    type: str
  status:
    description:
      - Whether the user account is enabled or disabled.
      - When omitted, the status of an existing user is left unmanaged
        (new users are created enabled).
    type: str
    choices:
      - enabled
      - disabled
  update_secret:
    description:
      - Rotate the secret of an B(existing) user to O(secret).
      - The module cannot read secrets back, so with this option the module
        always reports a change when the user exists.
    type: bool
    default: false
author:
  - David Igou (@david-igou)
"""

EXAMPLES = r"""
- name: Create an application user
  david_igou.rustfs.user:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEadminsecret
    name: app-backups
    secret: EXAMPLEusersecret

- name: Disable a user without touching its secret
  david_igou.rustfs.user:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEadminsecret
    name: app-backups
    status: disabled

- name: Remove a user
  david_igou.rustfs.user:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEadminsecret
    name: app-backups
    state: absent
"""

RETURN = r"""
user:
  description: User state after the module ran.
  returned: success
  type: dict
  contains:
    name:
      description: The user's access key.
      type: str
      sample: app-backups
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
        secret=dict(type="str", no_log=True),
        status=dict(type="str", choices=["enabled", "disabled"]),
        update_secret=dict(type="bool", default=False),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_if=[("update_secret", True, ["secret"])],
    )

    name = module.params["name"]
    state = module.params["state"]
    secret = module.params["secret"]
    status = module.params["status"]
    update_secret = module.params["update_secret"]

    result = dict(changed=False)

    try:
        client = RustfsAdminClient(module)
        existing = client.get_user(name)

        if state == "absent":
            if existing is not None:
                result["changed"] = True
                if not module.check_mode:
                    client.remove_user(name)
            module.exit_json(**result)

        # state == present
        if existing is None:
            if not secret:
                module.fail_json(
                    msg=(
                        "user %s needs to be created but no secret was provided - "
                        "the module takes resolved credentials only and never "
                        "generates them" % name
                    )
                )
            create_status = status or "enabled"
            result["changed"] = True
            if not module.check_mode:
                # add-user with the desired status directly.
                client.add_user(name, secret, status=create_status)
            result["user"] = dict(name=name, status=create_status, policies=[], member_of=[])
            module.exit_json(**result)

        # Existing user: the secret is never re-sent unless explicitly asked.
        if update_secret:
            result["changed"] = True
            if not module.check_mode:
                client.add_user(name, secret, status=status or existing["status"])
        if status is not None and existing["status"] != status:
            result["changed"] = True
            result["diff"] = dict(
                before=dict(status=existing["status"]),
                after=dict(status=status),
            )
            if not module.check_mode:
                client.set_user_status(name, status)

        result["user"] = dict(
            name=name,
            status=status or existing["status"],
            policies=existing["policies"],
            member_of=existing["member_of"],
        )
    except RustfsError as exc:
        module.fail_json(msg=to_native(exc))

    module.exit_json(**result)


def main():
    run_module()


if __name__ == "__main__":
    main()
