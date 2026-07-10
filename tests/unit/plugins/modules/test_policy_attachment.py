# GNU General Public License v3.0+
"""Unit tests for policy_attachment's union/exclusive set math."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import pytest

from ansible_collections.david_igou.rustfs.plugins.modules import (
    policy_attachment as attachment_module,
)
from ansible_collections.david_igou.rustfs.tests.unit.plugins.modules.utils import (
    AnsibleExitJson,
    AnsibleFailJson,
    patch_module_exit,
    set_module_args,
)


class FakeAdmin(object):
    def __init__(self, user=None, group=None):
        self.user = user
        self.group = group
        self.writes = []

    def __call__(self, module):
        return self

    def get_user(self, name):
        return self.user

    def get_group(self, name):
        return self.group

    def set_policy_attachment(self, policies, name, is_group):
        self.writes.append((sorted(policies), name, is_group))


def run(monkeypatch, fake, args, check_mode=False):
    patch_module_exit(monkeypatch)
    monkeypatch.setattr(attachment_module, "RustfsAdminClient", fake)
    set_module_args(args, check_mode=check_mode)
    with pytest.raises((AnsibleExitJson, AnsibleFailJson)) as ctx:
        attachment_module.main()
    return ctx.value


def test_union_preserves_out_of_band_attachments(monkeypatch):
    """The deletion-safety invariant: default mode writes current UNION
    desired, so an out-of-band extra survives the converge."""
    fake = FakeAdmin(user=dict(status="enabled", policies=["extra"], member_of=[]))
    outcome = run(monkeypatch, fake, dict(user="app", policies=["mine"]))
    assert outcome.result["changed"] is True
    assert fake.writes == [(["extra", "mine"], "app", False)]


def test_exclusive_detaches_extras(monkeypatch):
    fake = FakeAdmin(user=dict(status="enabled", policies=["extra", "mine"], member_of=[]))
    outcome = run(
        monkeypatch, fake, dict(user="app", policies=["mine"], exclusive=True)
    )
    assert outcome.result["changed"] is True
    assert fake.writes == [(["mine"], "app", False)]


def test_no_write_when_sets_already_equal(monkeypatch):
    fake = FakeAdmin(user=dict(status="enabled", policies=["b", "a"], member_of=[]))
    outcome = run(monkeypatch, fake, dict(user="app", policies=["a", "b"]))
    assert outcome.result["changed"] is False
    assert fake.writes == []


def test_group_target_sets_is_group(monkeypatch):
    fake = FakeAdmin(group=dict(name="devs", policies=[], members=[], status="enabled"))
    outcome = run(monkeypatch, fake, dict(group="devs", policies=["readwrite"]))
    assert outcome.result["changed"] is True
    assert fake.writes == [(["readwrite"], "devs", True)]


def test_empty_policies_refused(monkeypatch):
    outcome = run(monkeypatch, FakeAdmin(), dict(user="app", policies=[]))
    assert isinstance(outcome, AnsibleFailJson)
    assert "must not be empty" in outcome.result["msg"]


def test_missing_entity_fails(monkeypatch):
    outcome = run(monkeypatch, FakeAdmin(user=None), dict(user="ghost", policies=["p"]))
    assert isinstance(outcome, AnsibleFailJson)
    assert "does not exist" in outcome.result["msg"]


def test_check_mode_never_writes(monkeypatch):
    fake = FakeAdmin(user=dict(status="enabled", policies=[], member_of=[]))
    outcome = run(
        monkeypatch, fake, dict(user="app", policies=["p"]), check_mode=True
    )
    assert outcome.result["changed"] is True
    assert fake.writes == []
