#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the Ansible project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: rustfs_policy_attachment
short_description: Manage the policies attached to a RustFS user or group
description:
  - Reconcile the set of canned policies attached to an IAM user or group
    via the RustFS admin REST API.
  - The server's only attachment primitive is a B(full replace)
    (C(set-user-or-group-policy)) and there is no detach endpoint. The
    module reads the current attachment set and writes either the union of
    current and desired (the default - out-of-band attachments survive) or
    exactly O(policies) (O(exclusive=true) - which is how detaching works
    on RustFS).
version_added: "2.0.0"
extends_documentation_fragment:
  - david_igou.rustfs.rustfs
options:
  user:
    description:
      - Access key of the user to attach policies to.
      - Exactly one of O(user) and O(group) must be given.
    type: str
  group:
    description:
      - Name of the group to attach policies to.
    type: str
  policies:
    description:
      - Names of canned policies that must be attached.
      - Must not be empty. Detaching everything (an empty replace) has
        unverified server semantics and is refused.
    type: list
    elements: str
    required: true
  exclusive:
    description:
      - When V(false), attach O(policies) on top of whatever is already
        attached (union) - nothing is ever detached.
      - When V(true), make the attachment set exactly O(policies),
        detaching everything else.
    type: bool
    default: false
author:
  - David Igou (@david-igou)
"""

EXAMPLES = r"""
- name: Ensure the app policy is attached (out-of-band extras survive)
  david_igou.rustfs.rustfs_policy_attachment:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
    user: app-backups
    policies:
      - app-rw

- name: Make the attachment set exactly these policies (detaches extras)
  david_igou.rustfs.rustfs_policy_attachment:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
    user: app-backups
    policies:
      - app-rw
      - readonly
    exclusive: true

- name: Attach a policy to a group
  david_igou.rustfs.rustfs_policy_attachment:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
    group: developers
    policies:
      - readwrite
"""

RETURN = r"""
policies:
  description: Policies attached to the user or group after the module ran.
  returned: success
  type: list
  elements: str
  sample: [app-rw, readonly]
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
        user=dict(type="str"),
        group=dict(type="str"),
        policies=dict(type="list", elements="str", required=True),
        exclusive=dict(type="bool", default=False),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        mutually_exclusive=[("user", "group")],
        required_one_of=[("user", "group")],
    )

    user = module.params["user"]
    group = module.params["group"]
    policies = module.params["policies"]
    exclusive = module.params["exclusive"]

    if not policies:
        module.fail_json(
            msg=(
                "policies must not be empty - an empty full-replace (detach "
                "everything) has unverified semantics on RustFS"
            )
        )

    is_group = group is not None
    target = group if is_group else user

    result = dict(changed=False)

    try:
        client = RustfsAdminClient(module)
        if is_group:
            entity = client.get_group(target)
        else:
            entity = client.get_user(target)
        if entity is None:
            module.fail_json(
                msg="%s %s does not exist" % ("group" if is_group else "user", target)
            )

        current = entity["policies"]
        if exclusive:
            desired = sorted(set(policies))
        else:
            desired = sorted(set(current) | set(policies))

        result["policies"] = desired

        if set(desired) != set(current):
            result["changed"] = True
            result["diff"] = dict(
                before=dict(policies=sorted(current)),
                after=dict(policies=desired),
            )
            if not module.check_mode:
                client.set_policy_attachment(desired, target, is_group)
    except RustfsError as exc:
        module.fail_json(msg=to_native(exc))

    module.exit_json(**result)


def main():
    run_module()


if __name__ == "__main__":
    main()
