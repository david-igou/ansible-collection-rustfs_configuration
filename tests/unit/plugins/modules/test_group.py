# GNU General Public License v3.0+
"""Unit tests for the group module's append-vs-replace membership math."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import pytest

from ansible_collections.david_igou.rustfs.plugins.modules import group as group_module
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

    def get_group(self, name):
        return self.existing

    def create_group(self, name, members=None):
        self.calls.append(("create_group", name, members))

    def delete_group(self, name):
        self.calls.append(("delete_group", name))

    def set_group_status(self, name, status):
        self.calls.append(("set_group_status", name, status))

    def update_group_members(self, name, members, remove=False):
        self.calls.append(("update_members", name, sorted(members), remove))


def run(monkeypatch, fake, args, check_mode=False):
    patch_module_exit(monkeypatch)
    monkeypatch.setattr(group_module, "RustfsAdminClient", fake)
    set_module_args(args, check_mode=check_mode)
    with pytest.raises((AnsibleExitJson, AnsibleFailJson)) as ctx:
        group_module.main()
    return ctx.value


def existing(members, status="enabled"):
    return dict(name="devs", policies=[], members=members, status=status)


def test_replace_adds_and_removes(monkeypatch):
    fake = FakeAdmin(existing(["alice", "old"]))
    outcome = run(monkeypatch, fake, dict(name="devs", members=["alice", "bob"]))
    assert outcome.result["changed"] is True
    assert ("update_members", "devs", ["bob"], False) in fake.calls
    assert ("update_members", "devs", ["old"], True) in fake.calls
    assert outcome.result["group"]["members"] == ["alice", "bob"]


def test_append_only_adds(monkeypatch):
    fake = FakeAdmin(existing(["alice", "old"]))
    outcome = run(
        monkeypatch, fake, dict(name="devs", members=["bob"], append=True)
    )
    assert outcome.result["changed"] is True
    assert ("update_members", "devs", ["bob"], False) in fake.calls
    assert not any(call[3] for call in fake.calls if call[0] == "update_members")


def test_members_omitted_leaves_membership_unmanaged(monkeypatch):
    fake = FakeAdmin(existing(["alice"]))
    outcome = run(monkeypatch, fake, dict(name="devs"))
    assert outcome.result["changed"] is False
    assert fake.calls == []


def test_status_change(monkeypatch):
    fake = FakeAdmin(existing([], status="enabled"))
    outcome = run(monkeypatch, fake, dict(name="devs", status="disabled"))
    assert outcome.result["changed"] is True
    assert fake.calls == [("set_group_status", "devs", "disabled")]


def test_create_with_members(monkeypatch):
    fake = FakeAdmin(None)
    outcome = run(monkeypatch, fake, dict(name="devs", members=["alice"]))
    assert outcome.result["changed"] is True
    assert fake.calls == [("create_group", "devs", ["alice"])]


def test_absent_deletes(monkeypatch):
    fake = FakeAdmin(existing([]))
    outcome = run(monkeypatch, fake, dict(name="devs", state="absent"))
    assert outcome.result["changed"] is True
    assert fake.calls == [("delete_group", "devs")]
