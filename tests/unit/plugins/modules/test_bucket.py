# GNU General Public License v3.0+
"""Unit tests for the bucket module's versioning tri-state and absent path."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import pytest
from botocore.exceptions import ClientError

from ansible_collections.david_igou.rustfs.plugins.modules import bucket as bucket_module
from ansible_collections.david_igou.rustfs.tests.unit.plugins.modules.utils import (
    AnsibleExitJson,
    AnsibleFailJson,
    patch_module_exit,
    set_module_args,
)


def not_found():
    return ClientError(
        {"Error": {"Code": "404", "Message": "not found"},
         "ResponseMetadata": {"HTTPStatusCode": 404}},
        "HeadBucket",
    )


class FakeS3(object):
    def __init__(self, exists=True, versioning_status=None):
        self.exists = exists
        self.versioning_status = versioning_status
        self.calls = []

    def __call__(self, module):
        return self

    def head_bucket(self, Bucket):
        if not self.exists:
            raise not_found()

    def get_bucket_versioning(self, Bucket):
        return {"Status": self.versioning_status} if self.versioning_status else {}

    def create_bucket(self, Bucket):
        self.calls.append(("create_bucket", Bucket))
        self.exists = True

    def delete_bucket(self, Bucket):
        self.calls.append(("delete_bucket", Bucket))

    def put_bucket_versioning(self, Bucket, VersioningConfiguration):
        self.calls.append(("put_versioning", Bucket, VersioningConfiguration["Status"]))


def run(monkeypatch, fake, args, check_mode=False):
    patch_module_exit(monkeypatch)
    monkeypatch.setattr(bucket_module, "s3_client", fake)
    set_module_args(args, check_mode=check_mode)
    with pytest.raises((AnsibleExitJson, AnsibleFailJson)) as ctx:
        bucket_module.main()
    return ctx.value


def test_unconfigured_versioning_equals_suspended_noop(monkeypatch):
    """A never-configured bucket must compare equal to `suspended` - the
    tri-state collapse that keeps fresh buckets idempotent."""
    fake = FakeS3(exists=True, versioning_status=None)
    outcome = run(monkeypatch, fake, dict(name="b", versioning="suspended"))
    assert outcome.result["changed"] is False
    assert fake.calls == []


def test_enable_from_unconfigured_changes(monkeypatch):
    fake = FakeS3(exists=True, versioning_status=None)
    outcome = run(monkeypatch, fake, dict(name="b", versioning="enabled"))
    assert outcome.result["changed"] is True
    assert ("put_versioning", "b", "Enabled") in fake.calls


def test_versioning_omitted_is_unmanaged(monkeypatch):
    fake = FakeS3(exists=True, versioning_status="Enabled")
    outcome = run(monkeypatch, fake, dict(name="b"))
    assert outcome.result["changed"] is False
    assert fake.calls == []
    assert outcome.result["bucket"]["versioning"] == "enabled"


def test_create_when_missing(monkeypatch):
    fake = FakeS3(exists=False)
    outcome = run(monkeypatch, fake, dict(name="b"))
    assert outcome.result["changed"] is True
    assert ("create_bucket", "b") in fake.calls


def test_absent_deletes_existing(monkeypatch):
    fake = FakeS3(exists=True)
    outcome = run(monkeypatch, fake, dict(name="b", state="absent"))
    assert outcome.result["changed"] is True
    assert fake.calls == [("delete_bucket", "b")]


def test_absent_on_missing_is_noop(monkeypatch):
    fake = FakeS3(exists=False)
    outcome = run(monkeypatch, fake, dict(name="b", state="absent"))
    assert outcome.result["changed"] is False
    assert fake.calls == []


def test_check_mode_never_mutates(monkeypatch):
    fake = FakeS3(exists=False)
    outcome = run(
        monkeypatch, fake, dict(name="b", versioning="enabled"), check_mode=True
    )
    assert outcome.result["changed"] is True
    assert fake.calls == []
