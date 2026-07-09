#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: Contributors to the Ansible project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: rustfs_policy_info
short_description: Gather information about canned IAM policies on a RustFS server
description:
  - List canned policies, or fetch one policy's document (raw and
    canonicalized for comparison).
version_added: "2.0.0"
extends_documentation_fragment:
  - david_igou.rustfs.rustfs
options:
  name:
    description:
      - Name of a single policy to fetch.
      - When omitted, all policies are listed.
    type: str
author:
  - David Igou (@david-igou)
"""

EXAMPLES = r"""
- name: List all canned policies
  david_igou.rustfs.rustfs_policy_info:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
  register: all_policies

- name: Fetch one policy
  david_igou.rustfs.rustfs_policy_info:
    endpoint: https://nas.example.net:20292
    access_key: admin
    secret_key: EXAMPLEsecret
    name: app-rw
  register: app_rw
"""

RETURN = r"""
policies:
  description: Names of all canned policies on the server.
  returned: when O(name) is omitted
  type: list
  elements: str
  sample: [app-rw, readonly, readwrite]
builtin_policies:
  description: Names of the policies shipped with the server.
  returned: when O(name) is omitted
  type: list
  elements: str
  sample: [readonly, readwrite, writeonly, diagnostics, consoleAdmin]
policy:
  description: Detail for the requested policy.
  returned: when O(name) is given
  type: dict
  contains:
    name:
      description: Policy name.
      type: str
      sample: app-rw
    exists:
      description: Whether the policy exists.
      type: bool
      sample: true
    document:
      description: The policy document as stored on the server.
      type: dict
      sample: {}
    document_canonical:
      description: The policy document canonicalized for comparison.
      type: dict
      sample: {}
"""

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.common.text.converters import to_native

from ansible_collections.david_igou.rustfs.plugins.module_utils.canonical import (
    canonical_policy,
)
from ansible_collections.david_igou.rustfs.plugins.module_utils.rustfs import (
    BUILTIN_POLICIES,
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
            result["policies"] = sorted(client.list_policies())
            result["builtin_policies"] = list(BUILTIN_POLICIES)
        else:
            document = client.get_policy(name)
            policy = dict(name=name, exists=document is not None)
            if document is not None:
                policy["document"] = document
                policy["document_canonical"] = canonical_policy(document)
            result["policy"] = policy
    except RustfsError as exc:
        module.fail_json(msg=to_native(exc))

    module.exit_json(**result)


def main():
    run_module()


if __name__ == "__main__":
    main()
