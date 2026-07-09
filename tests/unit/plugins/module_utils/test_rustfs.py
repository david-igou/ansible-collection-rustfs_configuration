# GNU General Public License v3.0+
"""Unit tests for the RustFS client plumbing (error taxonomy, retries,
admin-client serde, SigV4 request shape)."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import io
import json

import pytest
from ansible.module_utils.six.moves.urllib.error import HTTPError

from ansible_collections.david_igou.rustfs_configuration.plugins.module_utils import rustfs
from ansible_collections.david_igou.rustfs_configuration.plugins.module_utils.rustfs import (
    RustfsAdminClient,
    RustfsAuthError,
    RustfsConflictError,
    RustfsError,
    RustfsNetworkError,
    RustfsNotFoundError,
    retry_call,
)

PARAMS = dict(
    endpoint="http://127.0.0.1:9100",
    access_key="ak",
    secret_key="sk",
    region="us-east-1",
    validate_certs=True,
    ca_bundle=None,
    retries=3,
    retry_delay=0,
)


class FakeModule(object):
    def __init__(self, params=None):
        self.params = dict(PARAMS, **(params or {}))

    def fail_json(self, **kwargs):
        raise AssertionError("fail_json: %s" % kwargs.get("msg"))


def http_error(status, body=b""):
    return HTTPError("http://x", status, "reason", hdrs=None, fp=io.BytesIO(body))


# -- retry_call ----------------------------------------------------------------


def test_retry_call_retries_network_errors_then_succeeds():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RustfsNetworkError("refused")
        return "ok"

    assert retry_call(PARAMS, flaky) == "ok"
    assert len(calls) == 3


def test_retry_call_exhausts_budget():
    calls = []

    def dead():
        calls.append(1)
        raise RustfsNetworkError("refused")

    with pytest.raises(RustfsNetworkError):
        retry_call(PARAMS, dead)
    assert len(calls) == PARAMS["retries"]


def test_retry_call_never_retries_permanent_errors():
    calls = []

    def denied():
        calls.append(1)
        raise RustfsAuthError("403")

    with pytest.raises(RustfsAuthError):
        retry_call(PARAMS, denied)
    assert len(calls) == 1


# -- HTTP error classification (admin plane, mirrors rc's map_error) -------------


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, RustfsAuthError),
        (403, RustfsAuthError),
        (404, RustfsNotFoundError),
        (409, RustfsConflictError),
        (400, RustfsError),
        (500, RustfsError),
        (502, RustfsNetworkError),
        (503, RustfsNetworkError),
        (504, RustfsNetworkError),
    ],
)
def test_classify_http(status, expected):
    exc = RustfsAdminClient._classify_http(http_error(status))
    assert exc.__class__ is expected


# -- admin client: request shape and serde ----------------------------------------


def test_admin_request_is_signed_and_shaped(monkeypatch):
    """PUT /add-user: URL, SigV4 headers, camelCase JSON body."""
    captured = {}

    def fake_open_url(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return io.BytesIO(b"")

    monkeypatch.setattr(rustfs, "open_url", fake_open_url)
    client = RustfsAdminClient(FakeModule())
    client.add_user("app-user", "s3cret")

    assert captured["url"] == (
        "http://127.0.0.1:9100/rustfs/admin/v3/add-user?accessKey=app-user"
    )
    assert captured["method"] == "PUT"
    assert json.loads(captured["data"]) == {"secretKey": "s3cret", "status": "enabled"}
    headers = dict((k.lower(), v) for k, v in captured["headers"].items())
    assert headers["content-type"] == "application/json"
    assert "AWS4-HMAC-SHA256" in headers["authorization"]
    assert "x-amz-content-sha256" in headers
    assert "x-amz-date" in headers


def test_admin_get_uses_empty_body_hash(monkeypatch):
    captured = {}

    def fake_open_url(url, **kwargs):
        captured.update(kwargs, url=url)
        return io.BytesIO(json.dumps({"status": "enabled"}).encode())

    monkeypatch.setattr(rustfs, "open_url", fake_open_url)
    client = RustfsAdminClient(FakeModule())
    client.get_user("app-user")

    headers = dict((k.lower(), v) for k, v in captured["headers"].items())
    # hex SHA256 of the empty string - required by the admin API on
    # body-less requests.
    assert headers["x-amz-content-sha256"] == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    assert captured["data"] is None


def test_list_users_transforms_map_and_splits_policies(monkeypatch):
    payload = {
        "app-user": {"status": "enabled", "policyName": "a,b", "memberOf": ["g"]},
        "other": {"status": "disabled", "policyName": None},
    }

    def fake_open_url(url, **kwargs):
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(rustfs, "open_url", fake_open_url)
    users = RustfsAdminClient(FakeModule()).list_users()
    assert users["app-user"] == dict(status="enabled", policies=["a", "b"], member_of=["g"])
    assert users["other"] == dict(status="disabled", policies=[], member_of=[])


def test_get_policy_unwraps_metadata_envelope(monkeypatch):
    """info-canned-policy answers {policy_name, policy: <doc>, create_date,
    update_date} (verified live on 1.0.0-beta.8) - callers get the doc."""
    envelope = {
        "policy_name": "app-rw",
        "policy": {"Version": "2012-10-17", "Statement": []},
        "create_date": "2026-07-09 20:15:27 +00:00:00",
        "update_date": "2026-07-09 20:15:27 +00:00:00",
    }

    def fake_open_url(url, **kwargs):
        return io.BytesIO(json.dumps(envelope).encode())

    monkeypatch.setattr(rustfs, "open_url", fake_open_url)
    assert RustfsAdminClient(FakeModule()).get_policy("app-rw") == envelope["policy"]


def test_get_policy_returns_none_on_404(monkeypatch):
    def fake_open_url(url, **kwargs):
        raise http_error(404)

    monkeypatch.setattr(rustfs, "open_url", fake_open_url)
    assert RustfsAdminClient(FakeModule()).get_policy("nope") is None


def test_get_policy_returns_none_on_500_does_not_exist(monkeypatch):
    """beta-8 answers a missing canned policy with HTTP 500 InternalError
    ("policy does not exist"), not 404 - observed live in molecule."""

    def fake_open_url(url, **kwargs):
        raise http_error(500, b"<Error><Code>InternalError</Code><Message>policy does not exist</Message></Error>")

    monkeypatch.setattr(rustfs, "open_url", fake_open_url)
    assert RustfsAdminClient(FakeModule()).get_policy("nope") is None


def test_get_user_other_500_still_raises(monkeypatch):
    def fake_open_url(url, **kwargs):
        raise http_error(500, b"disk exploded")

    monkeypatch.setattr(rustfs, "open_url", fake_open_url)
    with pytest.raises(RustfsError):
        RustfsAdminClient(FakeModule()).get_user("app-user")


def test_admin_retries_503_then_succeeds(monkeypatch):
    calls = []

    def fake_open_url(url, **kwargs):
        calls.append(1)
        if len(calls) < 2:
            raise http_error(503)
        return io.BytesIO(b"{}")

    monkeypatch.setattr(rustfs, "open_url", fake_open_url)
    assert RustfsAdminClient(FakeModule()).list_policies() == {}
    assert len(calls) == 2


def test_service_account_body_always_carries_expiration(monkeypatch):
    captured = {}

    def fake_open_url(url, **kwargs):
        captured.update(kwargs, url=url)
        return io.BytesIO(b"")

    monkeypatch.setattr(rustfs, "open_url", fake_open_url)
    RustfsAdminClient(FakeModule()).create_service_account("svc", "s3cret")
    body = json.loads(captured["data"])
    assert "expiration" in body and body["expiration"] is None


def test_set_policy_attachment_query_shape(monkeypatch):
    captured = {}

    def fake_open_url(url, **kwargs):
        captured["url"] = url
        return io.BytesIO(b"")

    monkeypatch.setattr(rustfs, "open_url", fake_open_url)
    RustfsAdminClient(FakeModule()).set_policy_attachment(["a", "b"], "app-user", False)
    assert captured["url"].endswith(
        "/set-user-or-group-policy?policyName=a%2Cb&userOrGroup=app-user&isGroup=false"
    )


# -- S3 exception classification ---------------------------------------------------


def test_classify_s3_exception_client_errors():
    from botocore.exceptions import ClientError

    def client_error(code, status):
        return ClientError(
            {"Error": {"Code": code, "Message": "m"}, "ResponseMetadata": {"HTTPStatusCode": status}},
            "OpName",
        )

    assert rustfs.classify_s3_exception(client_error("NoSuchBucket", 404)).__class__ is RustfsNotFoundError
    assert rustfs.classify_s3_exception(client_error("AccessDenied", 403)).__class__ is RustfsAuthError
    assert rustfs.classify_s3_exception(client_error("InvalidAccessKeyId", 403)).__class__ is RustfsAuthError
    assert rustfs.classify_s3_exception(client_error("SlowDown", 503)).__class__ is RustfsNetworkError
    assert rustfs.classify_s3_exception(client_error("Whatever", 400)).__class__ is RustfsError


def test_classify_s3_exception_endpoint_error_is_network():
    from botocore.exceptions import EndpointConnectionError

    exc = EndpointConnectionError(endpoint_url="http://x")
    assert rustfs.classify_s3_exception(exc).__class__ is RustfsNetworkError
