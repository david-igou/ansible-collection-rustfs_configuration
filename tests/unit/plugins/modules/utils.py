# GNU General Public License v3.0+
"""Standard AnsibleModule unit-test harness (set args, capture exits)."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json

from ansible.module_utils import basic
from ansible.module_utils.common.text.converters import to_bytes

CONN_ARGS = dict(
    endpoint="http://127.0.0.1:9100",
    access_key="admin-ak",
    secret_key="admin-sk",
    retries=1,
    retry_delay=0,
)


class AnsibleExitJson(Exception):
    """Raised in place of exit_json; carries the result dict."""

    @property
    def result(self):
        return self.args[0]


class AnsibleFailJson(Exception):
    """Raised in place of fail_json; carries the result dict."""

    @property
    def result(self):
        return self.args[0]


def set_module_args(args, check_mode=False):
    merged = dict(CONN_ARGS, **args)
    if check_mode:
        merged["_ansible_check_mode"] = True
    basic._ANSIBLE_ARGS = to_bytes(json.dumps({"ANSIBLE_MODULE_ARGS": merged}))
    # ansible-core >= 2.19 refuses module args without a serialization
    # profile (data tagging); plain JSON decodes fine under "legacy".
    if hasattr(basic, "_ANSIBLE_PROFILE"):
        basic._ANSIBLE_PROFILE = "legacy"


def exit_json(*args, **kwargs):
    kwargs.setdefault("changed", False)
    raise AnsibleExitJson(kwargs)


def fail_json(*args, **kwargs):
    kwargs["failed"] = True
    raise AnsibleFailJson(kwargs)


def patch_module_exit(monkeypatch):
    monkeypatch.setattr(basic.AnsibleModule, "exit_json", exit_json)
    monkeypatch.setattr(basic.AnsibleModule, "fail_json", fail_json)
