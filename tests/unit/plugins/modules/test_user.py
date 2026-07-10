# GNU General Public License v3.0+
"""Unit tests for the user module's create/rotate/status state machine."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import pytest

from ansible_collections.david_igou.rustfs.plugins.modules import user as user_module
from ansible_collections.david_igou.rustfs.tests.unit.plugins.modules.utils import (
    AnsibleExitJson,
    AnsibleFailJson,
    patch_module_exit,
    set_module_args,
)


class FakeAdmin(object):
    def __init__(self, existing=None):
        self.existing = existing
        self.calls = []

    def __call__(self, module):
        return self

    def get_user(self, name):
        return self.existing

    def add_user(self, name, secret, status="enabled"):
        self.calls.append(("add_user", name, secret, status))

    def remove_user(self, name):
        self.calls.append(("remove_user", name))

    def set_user_status(self, name, status):
        self.calls.append(("set_user_status", name, status))


def run(monkeypatch, fake, args, check_mode=False):
    patch_module_exit(monkeypatch)
    monkeypatch.setattr(user_module, "RustfsAdminClient", fake)
    set_module_args(args, check_mode=check_mode)
    with pytest.raises((AnsibleExitJson, AnsibleFailJson)) as ctx:
        user_module.main()
    return ctx.value


def test_create_without_secret_fails(monkeypatch):
    outcome = run(monkeypatch, FakeAdmin(existing=None), dict(name="app"))
    assert isinstance(outcome, AnsibleFailJson)
    assert "no secret" in outcome.result["msg"]


def test_create_defaults_status_to_enabled(monkeypatch):
    fake = FakeAdmin(existing=None)
    outcome = run(monkeypatch, fake, dict(name="app", secret="s3cret"))
    assert outcome.result["changed"] is True
    assert fake.calls == [("add_user", "app", "s3cret", "enabled")]


def test_existing_user_secret_never_resent_without_optin(monkeypatch):
    fake = FakeAdmin(existing=dict(status="enabled", policies=["p"], member_of=[]))
    outcome = run(monkeypatch, fake, dict(name="app", secret="s3cret"))
    assert outcome.result["changed"] is False
    assert fake.calls == []


def test_update_secret_always_changed_and_keeps_status(monkeypatch):
    fake = FakeAdmin(existing=dict(status="disabled", policies=[], member_of=[]))
    outcome = run(
        monkeypatch, fake, dict(name="app", secret="new", update_secret=True)
    )
    assert outcome.result["changed"] is True
    # status omitted -> the rotation re-add must carry the EXISTING status.
    assert ("add_user", "app", "new", "disabled") in fake.calls
    assert not any(c[0] == "set_user_status" for c in fake.calls)


def test_status_change_emits_diff_and_calls_set_status(monkeypatch):
    fake = FakeAdmin(existing=dict(status="enabled", policies=[], member_of=[]))
    outcome = run(monkeypatch, fake, dict(name="app", status="disabled"))
    assert outcome.result["changed"] is True
    assert outcome.result["diff"] == dict(
        before=dict(status="enabled"), after=dict(status="disabled")
    )
    assert fake.calls == [("set_user_status", "app", "disabled")]


def test_status_omitted_leaves_disabled_user_alone(monkeypatch):
    fake = FakeAdmin(existing=dict(status="disabled", policies=[], member_of=[]))
    outcome = run(monkeypatch, fake, dict(name="app"))
    assert outcome.result["changed"] is False
    assert fake.calls == []
    assert outcome.result["user"]["status"] == "disabled"


def test_absent_removes_existing(monkeypatch):
    fake = FakeAdmin(existing=dict(status="enabled", policies=[], member_of=[]))
    outcome = run(monkeypatch, fake, dict(name="app", state="absent"))
    assert outcome.result["changed"] is True
    assert fake.calls == [("remove_user", "app")]


def test_check_mode_makes_no_mutating_calls(monkeypatch):
    fake = FakeAdmin(existing=None)
    outcome = run(
        monkeypatch, fake, dict(name="app", secret="s3cret"), check_mode=True
    )
    assert outcome.result["changed"] is True
    assert fake.calls == []
