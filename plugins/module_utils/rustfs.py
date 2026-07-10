# -*- coding: utf-8 -*-

# GNU General Public License v3.0+
# (see https://www.gnu.org/licenses/gpl-3.0.txt)
"""Shared client plumbing for the modules.

RustFS exposes two management planes and the modules speak both directly
(no ``rc`` binary anywhere):

* the **S3 data plane** (buckets, versioning, lifecycle) - stock S3 API
  calls, driven through a botocore client;
* the **admin REST API** under ``/rustfs/admin/v3`` (users, canned
  policies, attachments, groups, service accounts, quota) - plain-JSON
  bodies with camelCase keys, authenticated with AWS SigV4 exactly like
  the S3 plane (service name ``s3``). Unlike MinIO's madmin, RustFS admin
  bodies are NOT encrypted, so no crypto beyond request signing is needed.

Error taxonomy mirrors the rc CLI's CI-protected exit codes, translated to
exceptions. Only transport-level failures (connection refused/reset,
timeouts, HTTP 502/503/504) are retryable - the RustFS admin API is known
to refuse connections in bursts on 1.0.0-beta.8 while the S3 data path
stays healthy. Everything else is permanent and fails fast.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import hashlib
import json
import socket
import time
import traceback

from ansible.module_utils.basic import env_fallback, missing_required_lib
from ansible.module_utils.common.text.converters import to_native, to_text
from ansible.module_utils.six.moves.urllib.error import HTTPError, URLError
from ansible.module_utils.six.moves.urllib.parse import quote, urlencode
from ansible.module_utils.urls import open_url

BOTOCORE_IMP_ERR = None
try:
    import botocore.session
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    from botocore.config import Config
    from botocore.credentials import Credentials
    from botocore.exceptions import BotoCoreError, ClientError

    HAS_BOTOCORE = True
except ImportError:
    HAS_BOTOCORE = False
    BOTOCORE_IMP_ERR = traceback.format_exc()

ADMIN_BASE_PATH = "/rustfs/admin/v3"

# Policies shipped with the server (useful to callers building reports).
BUILTIN_POLICIES = ("readonly", "readwrite", "writeonly", "diagnostics", "consoleAdmin")


class RustfsError(Exception):
    """Permanent RustFS API error."""


class RustfsNetworkError(RustfsError):
    """Transport-level failure - the only retryable class."""


class RustfsAuthError(RustfsError):
    """Authentication or authorization failure (HTTP 401/403)."""


class RustfsNotFoundError(RustfsError):
    """Resource does not exist (HTTP 404)."""


class RustfsConflictError(RustfsError):
    """Conflicting state (HTTP 409)."""


def rustfs_argument_spec():
    """Connection argument spec shared by every module in this collection."""
    return dict(
        endpoint=dict(
            type="str",
            required=True,
            fallback=(env_fallback, ["RUSTFS_ENDPOINT"]),
        ),
        access_key=dict(
            type="str",
            required=True,
            no_log=False,
            fallback=(env_fallback, ["RUSTFS_ACCESS_KEY"]),
        ),
        secret_key=dict(
            type="str",
            required=True,
            no_log=True,
            fallback=(env_fallback, ["RUSTFS_SECRET_KEY"]),
        ),
        region=dict(
            type="str",
            default="us-east-1",
            fallback=(env_fallback, ["RUSTFS_REGION"]),
        ),
        validate_certs=dict(
            type="bool",
            default=True,
            fallback=(env_fallback, ["RUSTFS_VALIDATE_CERTS"]),
        ),
        ca_bundle=dict(
            type="path",
            fallback=(env_fallback, ["RUSTFS_CA_BUNDLE"]),
        ),
        retries=dict(
            type="int",
            default=8,
            fallback=(env_fallback, ["RUSTFS_RETRIES"]),
        ),
        retry_delay=dict(
            type="int",
            default=3,
            fallback=(env_fallback, ["RUSTFS_RETRY_DELAY"]),
        ),
    )


def ensure_botocore(module):
    if not HAS_BOTOCORE:
        module.fail_json(msg=missing_required_lib("botocore"), exception=BOTOCORE_IMP_ERR)


def retry_call(params, func):
    """Run func, retrying RustfsNetworkError up to params['retries'] attempts."""
    attempts = max(1, params["retries"])
    for attempt in range(attempts):
        try:
            return func()
        except RustfsNetworkError:
            if attempt >= attempts - 1:
                raise
            time.sleep(max(0, params["retry_delay"]))


class RustfsAdminClient(object):
    """SigV4-signed plain-JSON client for the /rustfs/admin/v3 API.

    Request contract (established from rc v0.1.25 source, admin.rs):
    query parameters individually URL-encoded; ``x-amz-content-sha256`` is
    the hex SHA256 of the exact body bytes (empty-body constant on
    GET/DELETE); ``content-type: application/json`` only when a body is
    present; signed for service ``s3`` in the configured region.
    """

    def __init__(self, module):
        ensure_botocore(module)
        params = module.params
        self.params = params
        self._endpoint = params["endpoint"].rstrip("/")
        self._credentials = Credentials(params["access_key"], params["secret_key"])
        self._region = params["region"]
        self._validate_certs = params["validate_certs"]
        self._ca_bundle = params["ca_bundle"]

    # -- transport ---------------------------------------------------------

    def request(self, method, path, query=None, body=None):
        return retry_call(self.params, lambda: self._request_once(method, path, query, body))

    def _request_once(self, method, path, query, body):
        url = self._endpoint + ADMIN_BASE_PATH + path
        if query:
            # Each k=v URL-encoded exactly as rc does (%20, not +) so the
            # canonical query string SigV4 signs matches what is sent.
            url += "?" + urlencode(query, quote_via=quote)

        if body is None:
            payload = b""
        elif isinstance(body, bytes):
            payload = body
        else:
            payload = json.dumps(body).encode("utf-8")

        request = AWSRequest(method=method, url=url, data=payload or None)
        request.headers["x-amz-content-sha256"] = hashlib.sha256(payload).hexdigest()
        if payload:
            request.headers["Content-Type"] = "application/json"
        SigV4Auth(self._credentials, "s3", self._region).add_auth(request)

        try:
            response = open_url(
                url,
                method=method,
                data=payload or None,
                headers=dict(request.headers),
                validate_certs=self._validate_certs,
                ca_path=self._ca_bundle,
                timeout=30,
            )
            raw = response.read()
        except HTTPError as exc:
            raise self._classify_http(exc)
        except (URLError, ConnectionError, socket.timeout, socket.error) as exc:
            raise RustfsNetworkError(
                "cannot reach %s: %s" % (self._endpoint, to_native(exc))
            )

        if not raw:
            return None
        return json.loads(to_text(raw))

    @staticmethod
    def _classify_http(exc):
        status = exc.code
        try:
            detail = to_text(exc.read()).strip()
        except Exception:  # pylint: disable=broad-except
            detail = ""
        message = "HTTP %s: %s" % (status, detail or exc.reason)
        if status in (401, 403):
            return RustfsAuthError(message)
        if status == 404:
            return RustfsNotFoundError(message)
        if status == 409:
            return RustfsConflictError(message)
        if status in (502, 503, 504):
            return RustfsNetworkError(message)
        return RustfsError(message)

    # -- users --------------------------------------------------------------

    @staticmethod
    def _is_not_found(exc):
        """True when exc means the resource does not exist.

        The 1.0.0-beta.8 server does not answer 404 uniformly: a missing
        canned policy comes back as HTTP 500 InternalError with a
        "policy does not exist" body (observed live in molecule). Treat
        any permanent error carrying "does not exist" as not-found.
        """
        return isinstance(exc, RustfsNotFoundError) or "does not exist" in to_native(exc)

    @staticmethod
    def _policy_list(policy_name):
        return [p for p in (policy_name or "").split(",") if p]

    def list_users(self):
        """Return {access_key: {status, policies, member_of}}."""
        response = self.request("GET", "/list-users") or {}
        return dict(
            (
                access_key,
                dict(
                    status=info.get("status") or "enabled",
                    policies=self._policy_list(info.get("policyName")),
                    member_of=info.get("memberOf") or [],
                ),
            )
            for access_key, info in response.items()
        )

    def get_user(self, access_key):
        """Return the user dict, or None when it does not exist."""
        try:
            info = self.request("GET", "/user-info", query=[("accessKey", access_key)]) or {}
        except RustfsNetworkError:
            raise
        except RustfsError as exc:
            if self._is_not_found(exc):
                return None
            raise
        return dict(
            status=info.get("status") or "enabled",
            policies=self._policy_list(info.get("policyName")),
            member_of=info.get("memberOf") or [],
        )

    def add_user(self, access_key, secret_key, status="enabled"):
        # NOTE: add-user on an EXISTING access key rotates its secret in
        # place - callers must guard (user only calls this on create
        # or with an explicit update_secret opt-in).
        self.request(
            "PUT",
            "/add-user",
            query=[("accessKey", access_key)],
            body={"secretKey": secret_key, "status": status},
        )

    def remove_user(self, access_key):
        self.request("DELETE", "/remove-user", query=[("accessKey", access_key)])

    def set_user_status(self, access_key, status):
        self.request(
            "PUT",
            "/set-user-status",
            query=[("accessKey", access_key), ("status", status)],
        )

    # -- canned policies -----------------------------------------------------

    def list_policies(self):
        """Return {name: document} of all canned policies."""
        return self.request("GET", "/list-canned-policies") or {}

    def get_policy(self, name):
        """Return the policy document dict, or None when it does not exist."""
        try:
            response = self.request("GET", "/info-canned-policy", query=[("name", name)])
        except RustfsNetworkError:
            raise
        except RustfsError as exc:
            if self._is_not_found(exc):
                return None
            raise
        # The server answers with a metadata wrapper (verified live on
        # 1.0.0-beta.8): {policy_name, policy: <document>, create_date,
        # update_date}. Unwrap to the document itself.
        if isinstance(response, dict) and "policy" in response and "policy_name" in response:
            return response["policy"]
        return response

    def put_policy(self, name, document):
        # Body is the raw policy JSON document itself (no wrapper).
        self.request(
            "PUT",
            "/add-canned-policy",
            query=[("name", name)],
            body=json.dumps(document).encode("utf-8"),
        )

    def delete_policy(self, name):
        self.request("DELETE", "/remove-canned-policy", query=[("name", name)])

    def set_policy_attachment(self, policies, name, is_group):
        """FULL-REPLACE of the user's/group's attached policy set.

        The server has no detach endpoint (rc's detach is a stub returning
        UnsupportedFeature) - replacing with the remaining set IS detach.
        """
        self.request(
            "PUT",
            "/set-user-or-group-policy",
            query=[
                ("policyName", ",".join(policies)),
                ("userOrGroup", name),
                ("isGroup", "true" if is_group else "false"),
            ],
        )

    # -- groups ---------------------------------------------------------------

    def list_groups(self):
        return self.request("GET", "/groups") or []

    def get_group(self, name):
        """Return {name, policies, members, status}, or None."""
        try:
            info = self.request("GET", "/group", query=[("group", name)]) or {}
        except RustfsNetworkError:
            raise
        except RustfsError as exc:
            if self._is_not_found(exc):
                return None
            raise
        return dict(
            name=info.get("name") or name,
            policies=self._policy_list(info.get("policy")),
            members=info.get("members") or [],
            status=info.get("status") or "enabled",
        )

    def create_group(self, name, members=None):
        body = {"group": name}
        if members:
            body["members"] = list(members)
        self.request("POST", "/groups", body=body)

    def delete_group(self, name):
        self.request("DELETE", "/group/%s" % quote(name, safe=""))

    def set_group_status(self, name, status):
        self.request(
            "PUT",
            "/set-group-status",
            query=[("group", name), ("status", status)],
        )

    def update_group_members(self, name, members, remove=False):
        self.request(
            "PUT",
            "/update-group-members",
            body={
                "group": name,
                "members": list(members),
                "isRemove": bool(remove),
                "groupStatus": "enabled",
            },
        )

    # -- service accounts ------------------------------------------------------

    def list_service_accounts(self, user=None):
        query = [("user", user)] if user else None
        response = self.request("GET", "/list-service-accounts", query=query) or {}
        return response.get("accounts") or []

    def get_service_account(self, access_key):
        try:
            info = self.request(
                "GET", "/info-service-account", query=[("accessKey", access_key)]
            ) or {}
        except RustfsNetworkError:
            raise
        except RustfsError as exc:
            if self._is_not_found(exc):
                return None
            raise
        info.setdefault("accessKey", access_key)
        return info

    def create_service_account(self, access_key, secret_key, policy=None, name=None,
                               description=None, expiration=None):
        # The server requires the expiration key to be PRESENT (null when
        # unset) - serde on the rc side always emits it.
        body = {
            "accessKey": access_key,
            "secretKey": secret_key,
            "expiration": expiration,
        }
        if policy is not None:
            body["policy"] = json.dumps(policy)
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        return self.request("PUT", "/add-service-accounts", body=body)

    def delete_service_account(self, access_key):
        self.request("DELETE", "/delete-service-accounts", query=[("accessKey", access_key)])

    # -- bucket quota ------------------------------------------------------------

    def get_bucket_quota(self, bucket):
        """Return the BucketQuota dict; quota is None/0 when unlimited."""
        try:
            return self.request("GET", "/quota/%s" % quote(bucket, safe=""))
        except RustfsNetworkError:
            raise
        except RustfsError as exc:
            if self._is_not_found(exc):
                return None
            raise

    def set_bucket_quota(self, bucket, quota_bytes):
        return self.request(
            "PUT",
            "/quota/%s" % quote(bucket, safe=""),
            body={"quota": int(quota_bytes), "quotaType": "HARD"},
        )

    def clear_bucket_quota(self, bucket):
        return self.request("DELETE", "/quota/%s" % quote(bucket, safe=""))


# -- S3 data plane -----------------------------------------------------------

# S3 error codes that mean "credentials are wrong" (as opposed to "valid
# but unauthorized" - rc's alias-set validation treats AccessDenied as
# valid credentials, and credential_info makes the same call).
S3_BAD_CREDENTIAL_CODES = (
    "InvalidAccessKeyId",
    "SignatureDoesNotMatch",
    "InvalidToken",
    "ExpiredToken",
)

S3_ACCESS_DENIED_CODES = ("AccessDenied", "AllAccessDisabled")

_S3_NOT_FOUND_CODES = (
    "NoSuchBucket",
    "NoSuchKey",
    "NoSuchLifecycleConfiguration",
    "404",
    "NotFound",
)

_S3_RETRYABLE_CODES = ("SlowDown", "ServiceUnavailable", "RequestTimeout", "503")


def s3_client(module):
    """botocore S3 client aimed at the RustFS endpoint.

    Path-style addressing matches rc's default bucket lookup; botocore's
    own retries are disabled so retry behavior is uniform with the admin
    client (retry_call / s3_call).
    """
    ensure_botocore(module)
    params = module.params
    if params["ca_bundle"]:
        verify = params["ca_bundle"]
    else:
        verify = params["validate_certs"]
    session = botocore.session.get_session()
    return session.create_client(
        "s3",
        endpoint_url=params["endpoint"],
        region_name=params["region"],
        aws_access_key_id=params["access_key"],
        aws_secret_access_key=params["secret_key"],
        verify=verify,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"total_max_attempts": 1},
            connect_timeout=30,
            read_timeout=30,
        ),
    )


def classify_s3_exception(exc):
    """Map a botocore exception onto the RustFS error taxonomy."""
    if isinstance(exc, ClientError):
        error = exc.response.get("Error", {})
        code = error.get("Code", "")
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        message = "%s: %s" % (code or status, error.get("Message", to_native(exc)))
        if code in S3_BAD_CREDENTIAL_CODES or code in S3_ACCESS_DENIED_CODES:
            return RustfsAuthError(message)
        if code in _S3_NOT_FOUND_CODES or status == 404:
            return RustfsNotFoundError(message)
        if status == 409:
            return RustfsConflictError(message)
        if code in _S3_RETRYABLE_CODES or status in (502, 503, 504):
            return RustfsNetworkError(message)
        return RustfsError(message)
    if isinstance(exc, BotoCoreError):
        name = exc.__class__.__name__
        if name in (
            "EndpointConnectionError",
            "ConnectTimeoutError",
            "ReadTimeoutError",
            "ConnectionClosedError",
            "ProxyConnectionError",
        ):
            return RustfsNetworkError(to_native(exc))
        return RustfsError(to_native(exc))
    return RustfsError(to_native(exc))


def s3_call(params, func):
    """Run an S3 client call with taxonomy classification and retries."""

    def attempt():
        try:
            return func()
        except (ClientError, BotoCoreError) as exc:
            raise classify_s3_exception(exc)

    return retry_call(params, attempt)


def error_code(exc):
    """Return the ClientError code string, or '' for other exceptions."""
    if HAS_BOTOCORE and isinstance(exc, ClientError):
        return exc.response.get("Error", {}).get("Code", "")
    return ""
