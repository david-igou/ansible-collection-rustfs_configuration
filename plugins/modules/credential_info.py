#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the Ansible project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: credential_info
short_description: Verify a credential pair against a RustFS server (liveness)
description:
  - Prove that the access-key/secret-key pair the module authenticates
    with actually works against the server - catching divergence between a
    credential store and the server (out-of-band rotation, stale item,
    wedged server).
  - The probe distinguishes I(authentication) (the pair is cryptographically
    valid) from I(authorization) (the pair may do what was asked) - a
    distinction the rc CLI's exit codes lump together.
  - Optionally proves the credential can list a specific bucket.
  - Unlike the other modules, O(access_key)/O(secret_key) here are the
    B(probed) pair, not an admin credential.
version_added: "2.0.0"
extends_documentation_fragment:
  - david_igou.rustfs.rustfs
options:
  bucket:
    description:
      - Bucket the credential must be able to list.
      - When omitted, only authentication is probed.
    type: str
author:
  - David Igou (@david-igou)
"""

EXAMPLES = r"""
- name: Verify a user credential can list its bucket
  david_igou.rustfs.credential_info:
    endpoint: https://nas.example.net:20292
    access_key: app-backups
    secret_key: EXAMPLEusersecret
    bucket: backups
  register: liveness

- name: Fail on dead credentials
  ansible.builtin.assert:
    that: liveness.credential.usable
"""

RETURN = r"""
credential:
  description: Probe outcome.
  returned: success
  type: dict
  contains:
    authenticated:
      description:
        - Whether the pair is valid on the server (signature accepted).
        - An V(AccessDenied) still counts as authenticated - the pair is
          real, just not authorized for the probed action.
      type: bool
      sample: true
    authorized:
      description:
        - Whether the probed actions were authorized.
        - V(null) when authentication already failed.
      type: bool
      sample: true
    bucket_listable:
      description:
        - Whether O(bucket) could be listed with the pair.
        - Only returned when O(bucket) was given, V(null) when
          authentication already failed.
      type: bool
      sample: true
    usable:
      description: Overall verdict - authenticated and every probed action authorized.
      type: bool
      sample: true
    detail:
      description: Human-readable reason when the probe failed.
      type: str
      sample: ""
"""

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.common.text.converters import to_native

from ansible_collections.david_igou.rustfs.plugins.module_utils.rustfs import (
    RustfsAuthError,
    RustfsError,
    RustfsNotFoundError,
    S3_BAD_CREDENTIAL_CODES,
    rustfs_argument_spec,
    s3_call,
    s3_client,
)


def is_bad_credential(exc):
    """True when the auth error means the pair itself is invalid."""
    message = to_native(exc)
    return any(message.startswith("%s:" % code) for code in S3_BAD_CREDENTIAL_CODES)


def run_module():
    argument_spec = rustfs_argument_spec()
    argument_spec.update(
        bucket=dict(type="str"),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    bucket = module.params["bucket"]
    credential = dict(
        authenticated=False,
        authorized=None,
        usable=False,
        detail="",
    )
    if bucket is not None:
        credential["bucket_listable"] = None

    try:
        client = s3_client(module)

        # Authentication probe - same call rc's `alias set` validates with.
        try:
            s3_call(module.params, client.list_buckets)
            credential["authenticated"] = True
            credential["authorized"] = True
        except RustfsAuthError as exc:
            if is_bad_credential(exc):
                credential["detail"] = to_native(exc)
                module.exit_json(changed=False, credential=credential)
            # AccessDenied: the pair is valid, just not allowed to list all
            # buckets - authentication proven.
            credential["authenticated"] = True
            credential["authorized"] = False
            credential["detail"] = to_native(exc)

        if bucket is not None:
            try:
                s3_call(
                    module.params,
                    lambda: client.list_objects_v2(Bucket=bucket, MaxKeys=1),
                )
                credential["bucket_listable"] = True
                credential["authorized"] = True
                credential["detail"] = ""
            except (RustfsAuthError, RustfsNotFoundError) as exc:
                credential["bucket_listable"] = False
                credential["authorized"] = False
                credential["detail"] = to_native(exc)

        credential["usable"] = bool(
            credential["authenticated"]
            and credential["authorized"]
            and (bucket is None or credential["bucket_listable"])
        )
    except RustfsError as exc:
        module.fail_json(msg=to_native(exc), credential=credential)

    module.exit_json(changed=False, credential=credential)


def main():
    run_module()


if __name__ == "__main__":
    main()
