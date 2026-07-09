#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the Ansible project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: rustfs_bucket
short_description: Manage buckets on a RustFS server
description:
  - Create or remove buckets and manage their versioning state on a RustFS
    object-storage server, directly over the S3 API.
  - Existence is always decided by a read (the 1.0.0-beta.8 server returns
    false success for a create on an existing bucket), so repeated runs are
    idempotent.
version_added: "2.0.0"
extends_documentation_fragment:
  - david_igou.rustfs_configuration.rustfs
options:
  name:
    description:
      - Name of the bucket.
    type: str
    required: true
  state:
    description:
      - Whether the bucket should exist.
      - Removal fails cleanly when the bucket is not empty, and versioned
        buckets cannot be deleted on 1.0.0-beta.8 at all.
    type: str
    choices:
      - present
      - absent
    default: present
  versioning:
    description:
      - Desired versioning state of the bucket.
      - When omitted, versioning is left unmanaged.
      - A never-configured bucket compares equal to V(suspended).
    type: str
    choices:
      - enabled
      - suspended
author:
  - David Igou (@david-igou)
"""

EXAMPLES = r"""
- name: Create a bucket with versioning enabled
  david_igou.rustfs_configuration.rustfs_bucket:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
    name: backups
    versioning: enabled

- name: Ensure a bucket exists, versioning unmanaged
  david_igou.rustfs_configuration.rustfs_bucket:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
    name: scratch

- name: Remove a bucket
  david_igou.rustfs_configuration.rustfs_bucket:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
    name: scratch
    state: absent
"""

RETURN = r"""
bucket:
  description: State of the bucket after the module ran.
  returned: success
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
"""

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.common.text.converters import to_native

from ansible_collections.david_igou.rustfs_configuration.plugins.module_utils.rustfs import (
    RustfsError,
    RustfsNotFoundError,
    rustfs_argument_spec,
    s3_call,
    s3_client,
)


def bucket_exists(module, client):
    try:
        s3_call(module.params, lambda: client.head_bucket(Bucket=module.params["name"]))
        return True
    except RustfsNotFoundError:
        return False


def versioning_status(module, client):
    """Return 'enabled', 'suspended', or 'unconfigured'."""
    response = s3_call(
        module.params,
        lambda: client.get_bucket_versioning(Bucket=module.params["name"]),
    )
    status = response.get("Status")
    return status.lower() if status else "unconfigured"


def run_module():
    argument_spec = rustfs_argument_spec()
    argument_spec.update(
        name=dict(type="str", required=True),
        state=dict(type="str", choices=["present", "absent"], default="present"),
        versioning=dict(type="str", choices=["enabled", "suspended"]),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    name = module.params["name"]
    state = module.params["state"]
    versioning = module.params["versioning"]

    result = dict(changed=False, bucket=dict(name=name))

    try:
        client = s3_client(module)
        exists = bucket_exists(module, client)

        if state == "absent":
            result["bucket"]["exists"] = False
            if exists:
                result["changed"] = True
                if not module.check_mode:
                    try:
                        s3_call(module.params, lambda: client.delete_bucket(Bucket=name))
                    except RustfsError as exc:
                        module.fail_json(
                            msg=(
                                "cannot delete bucket %s: %s (non-empty buckets must be "
                                "emptied first; versioned buckets are undeletable on "
                                "RustFS 1.0.0-beta.8)" % (name, to_native(exc))
                            )
                        )
            module.exit_json(**result)

        # state == present
        current_versioning = None
        if not exists:
            result["changed"] = True
            if not module.check_mode:
                s3_call(module.params, lambda: client.create_bucket(Bucket=name))
                current_versioning = versioning_status(module, client)
        else:
            current_versioning = versioning_status(module, client)

        if versioning is not None:
            # A never-configured bucket is effectively suspended.
            effective = current_versioning if current_versioning not in (None, "unconfigured") else "suspended"
            if effective != versioning:
                result["changed"] = True
                result["diff"] = dict(
                    before=dict(versioning=current_versioning or "unconfigured"),
                    after=dict(versioning=versioning),
                )
                if not module.check_mode:
                    s3_call(
                        module.params,
                        lambda: client.put_bucket_versioning(
                            Bucket=name,
                            VersioningConfiguration=dict(Status=versioning.capitalize()),
                        ),
                    )
                current_versioning = versioning

        result["bucket"]["exists"] = True
        result["bucket"]["versioning"] = current_versioning or "unconfigured"
    except RustfsError as exc:
        module.fail_json(msg=to_native(exc))

    module.exit_json(**result)


def main():
    run_module()


if __name__ == "__main__":
    main()
