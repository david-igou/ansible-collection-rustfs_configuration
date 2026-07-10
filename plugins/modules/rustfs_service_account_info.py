#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the Ansible project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: rustfs_service_account_info
short_description: Gather information about service accounts on a RustFS server
description:
  - List service accounts (optionally filtered by parent user), or report
    one service account.
  - Secrets are never returned (the server does not expose them).
version_added: "2.0.0"
extends_documentation_fragment:
  - david_igou.rustfs.rustfs
options:
  name:
    description:
      - Access key of a single service account to inspect.
    type: str
  user:
    description:
      - When listing, only return service accounts belonging to this user.
      - Mutually exclusive with O(name).
    type: str
author:
  - David Igou (@david-igou)
"""

EXAMPLES = r"""
- name: List all service accounts of a user
  david_igou.rustfs.rustfs_service_account_info:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
    user: app-backups
  register: app_service_accounts

- name: Inspect one service account
  david_igou.rustfs.rustfs_service_account_info:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
    name: svc-backup-writer
  register: svc
"""

RETURN = r"""
service_accounts:
  description: Service accounts on the server (filtered by O(user) when given).
  returned: when O(name) is omitted
  type: list
  elements: dict
  sample:
    - access_key: svc-backup-writer
      parent_user: app-backups
      account_status: "on"
service_account:
  description: Detail for the requested service account.
  returned: when O(name) is given
  type: dict
  contains:
    access_key:
      description: The service account's access key.
      type: str
      sample: svc-backup-writer
    exists:
      description: Whether the service account exists.
      type: bool
      sample: true
    parent_user:
      description: Identity the account was created under.
      type: str
      sample: app-backups
    account_status:
      description: Account status as reported by the server.
      type: str
      sample: "on"
    expiration:
      description: Expiration timestamp, if any.
      type: str
      sample: "2027-01-01T00:00:00Z"
"""

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.common.text.converters import to_native

from ansible_collections.david_igou.rustfs.plugins.module_utils.rustfs import (
    RustfsAdminClient,
    RustfsError,
    rustfs_argument_spec,
)


def serialize(info):
    return dict(
        access_key=info.get("accessKey"),
        parent_user=info.get("parentUser"),
        account_status=info.get("accountStatus"),
        expiration=info.get("expiration"),
        name=info.get("name"),
        description=info.get("description"),
    )


def run_module():
    argument_spec = rustfs_argument_spec()
    argument_spec.update(
        name=dict(type="str"),
        user=dict(type="str"),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        mutually_exclusive=[("name", "user")],
    )

    name = module.params["name"]
    user = module.params["user"]
    result = dict(changed=False)

    try:
        client = RustfsAdminClient(module)
        if name is None:
            result["service_accounts"] = [
                serialize(info) for info in client.list_service_accounts(user=user)
            ]
        else:
            info = client.get_service_account(name)
            account = dict(access_key=name, exists=info is not None)
            if info is not None:
                account.update(serialize(info))
                account["exists"] = True
            result["service_account"] = account
    except RustfsError as exc:
        module.fail_json(msg=to_native(exc))

    module.exit_json(**result)


def main():
    run_module()


if __name__ == "__main__":
    main()
