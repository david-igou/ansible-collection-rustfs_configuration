# GNU General Public License v3.0+
"""Unit tests for credential_info's authentication-vs-authorization hinge."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import pytest

from ansible_collections.david_igou.rustfs.plugins.module_utils.rustfs import (
    S3_BAD_CREDENTIAL_CODES,
    RustfsAuthError,
)
from ansible_collections.david_igou.rustfs.plugins.modules.credential_info import (
    is_bad_credential,
)


@pytest.mark.parametrize("code", S3_BAD_CREDENTIAL_CODES)
def test_bad_credential_codes_mean_invalid_pair(code):
    assert is_bad_credential(RustfsAuthError("%s: rejected" % code)) is True


def test_access_denied_is_a_valid_pair():
    """AccessDenied means authenticated-but-unauthorized - the hinge that
    separates a dead credential from an under-privileged one."""
    assert is_bad_credential(RustfsAuthError("AccessDenied: not allowed")) is False


def test_code_must_be_a_prefix_not_a_substring():
    assert is_bad_credential(RustfsAuthError("something InvalidAccessKeyId")) is False


def test_disabled_account_is_a_verdict_not_a_failure():
    from ansible_collections.david_igou.rustfs.plugins.module_utils.rustfs import (
        RustfsError,
    )
    from ansible_collections.david_igou.rustfs.plugins.modules.credential_info import (
        is_disabled_account,
    )

    assert is_disabled_account(RustfsError("InvalidRequest: ErrAccessKeyDisabled"))
    assert not is_disabled_account(RustfsError("InvalidRequest: something else"))
