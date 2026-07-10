#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the Ansible project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: service_account
short_description: Manage service accounts on a RustFS server
description:
  - Create or remove service accounts (scoped access-key/secret pairs)
    via the RustFS admin REST API.
  - Service accounts are created under the identity the module
    authenticates as.
  - RustFS 0.1.x/1.0.0-beta.8 has no service-account update endpoint - an
    existing account is never modified, only reported. To change its
    policy or expiration, remove and recreate it.
  - The module never generates credentials, the secret arrives resolved
    from the caller.
version_added: "2.0.0"
extends_documentation_fragment:
  - david_igou.rustfs.rustfs
options:
  name:
    description:
      - The service account's access key.
    type: str
    required: true
  state:
    description:
      - Whether the service account should exist.
    type: str
    choices:
      - present
      - absent
    default: present
  secret:
    description:
      - The service account's secret key.
      - Required to create the account, ignored when it already exists.
    type: str
  policy:
    description:
      - Optional IAM policy document (dictionary) scoping the account below
        its parent identity's permissions.
      - Applied only at creation time (the server has no update endpoint).
    type: dict
  display_name:
    description:
      - Optional human-readable name, applied only at creation time.
    type: str
  description:
    description:
      - Optional description, applied only at creation time.
    type: str
  expiration:
    description:
      - Optional expiration timestamp (ISO 8601, for example
        V(2027-01-01T00:00:00Z)), applied only at creation time.
    type: str
author:
  - David Igou (@david-igou)
"""

EXAMPLES = r"""
- name: Create a scoped service account
  david_igou.rustfs.service_account:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEadminsecret
    name: svc-backup-writer
    secret: EXAMPLEsvcsecret
    description: Nightly backup writer
    policy:
      Version: "2012-10-17"
      Statement:
        - Effect: Allow
          Action: [s3:PutObject]
          Resource: [arn:aws:s3:::backups/*]

- name: Remove a service account
  david_igou.rustfs.service_account:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEadminsecret
    name: svc-backup-writer
    state: absent
"""

RETURN = r"""
service_account:
  description: Service account state after the module ran.
  returned: success and O(state=present)
  type: dict
  contains:
    access_key:
      description: The service account's access key.
      type: str
      sample: svc-backup-writer
    parent_user:
      description: Identity the account was created under.
      type: str
      sample: admin
    account_status:
      description: Account status as reported by the server.
      type: str
      sample: "on"
    expiration:
      description: Expiration timestamp, if any.
      type: str
      sample: "2027-01-01T00:00:00Z"
    name:
      description: Human-readable name, if any.
      type: str
      sample: backup writer
    description:
      description: Description, if any.
      type: str
      sample: Nightly backup writer
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
        name=dict(type="str", required=True),
        state=dict(type="str", choices=["present", "absent"], default="present"),
        secret=dict(type="str", no_log=True),
        policy=dict(type="dict"),
        display_name=dict(type="str"),
        description=dict(type="str"),
        expiration=dict(type="str"),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    name = module.params["name"]
    state = module.params["state"]
    secret = module.params["secret"]

    result = dict(changed=False)

    try:
        client = RustfsAdminClient(module)
        existing = client.get_service_account(name)

        if state == "absent":
            if existing is not None:
                result["changed"] = True
                if not module.check_mode:
                    client.delete_service_account(name)
            module.exit_json(**result)

        # state == present
        if existing is not None:
            # No update endpoint exists - report, never modify.
            result["service_account"] = serialize(existing)
            module.exit_json(**result)

        if not secret:
            module.fail_json(
                msg=(
                    "service account %s needs to be created but no secret was "
                    "provided - the module takes resolved credentials only and "
                    "never generates them" % name
                )
            )

        result["changed"] = True
        if not module.check_mode:
            client.create_service_account(
                name,
                secret,
                policy=module.params["policy"],
                name=module.params["display_name"],
                description=module.params["description"],
                expiration=module.params["expiration"],
            )
            created = client.get_service_account(name)
            if created is not None:
                result["service_account"] = serialize(created)
        if "service_account" not in result:
            result["service_account"] = dict(access_key=name)
    except RustfsError as exc:
        module.fail_json(msg=to_native(exc))

    module.exit_json(**result)


def main():
    run_module()


if __name__ == "__main__":
    main()
