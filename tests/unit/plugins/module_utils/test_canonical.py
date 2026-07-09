# GNU General Public License v3.0+
"""Unit tests for the shared canonicalization (S3 API shape)."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

from datetime import datetime, timezone

from ansible_collections.david_igou.rustfs.plugins.module_utils.canonical import (
    canonical_lifecycle_rules,
    canonical_policy,
)


def test_policy_server_echo_boilerplate_absorbed():
    """A from-scratch document equals the server echo with injected empties."""
    desired = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:PutObject", "s3:GetObject"],
                "Resource": ["arn:aws:s3:::app/*"],
            }
        ],
    }
    echo = {
        "ID": "",
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "",
                "Condition": {},
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject"],
                "Resource": ["arn:aws:s3:::app/*"],
            }
        ],
    }
    assert canonical_policy(desired) == canonical_policy(echo)


def test_policy_real_sid_and_condition_survive():
    doc = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "Named",
                "Effect": "Allow",
                "Action": ["s3:GetObject"],
                "Resource": ["arn:aws:s3:::app/*"],
                "Condition": {"Bool": {"aws:SecureTransport": "true"}},
            }
        ],
    }
    canonical = canonical_policy(doc)
    assert canonical["Statement"][0]["Sid"] == "Named"
    assert canonical["Statement"][0]["Condition"] == {"Bool": {"aws:SecureTransport": "true"}}


def test_ilm_ids_stripped_and_rules_sorted():
    a = [
        {"ID": "server-generated-1", "Status": "Enabled", "Prefix": "b/"},
        {"ID": "server-generated-2", "Status": "Enabled", "Prefix": "a/"},
    ]
    b = [
        {"Status": "Enabled", "Prefix": "a/"},
        {"Status": "Enabled", "Prefix": "b/"},
    ]
    assert canonical_lifecycle_rules(a) == canonical_lifecycle_rules(b)


def test_ilm_empty_scoping_absorbed():
    """Whole-bucket rules written with explicit empty scoping compare equal
    to the server's read (which omits empty Prefix/Filter entirely)."""
    spec = [{"Status": "Enabled", "Prefix": "", "Filter": {"Prefix": ""}, "Expiration": {"Days": 7}}]
    server = [{"ID": "x", "Status": "Enabled", "Expiration": {"Days": 7}}]
    assert canonical_lifecycle_rules(spec) == canonical_lifecycle_rules(server)


def test_ilm_nonempty_filter_survives():
    """A non-empty Filter is NOT masked - it must surface as drift when the
    server drops it (docs/server-quirks.md)."""
    rules = [{"Status": "Enabled", "Filter": {"Prefix": "logs/"}}]
    assert canonical_lifecycle_rules(rules)[0]["Filter"] == {"Prefix": "logs/"}


def test_ilm_dates_normalized_across_representations():
    """botocore returns datetimes on read; specs carry strings - both sides
    land on one canonical representation."""
    server = [
        {
            "ID": "x",
            "Status": "Enabled",
            "Expiration": {"Date": datetime(2026, 1, 1, tzinfo=timezone.utc)},
        }
    ]
    spec_date_only = [{"Status": "Enabled", "Expiration": {"Date": "2026-01-01"}}]
    spec_full = [{"Status": "Enabled", "Expiration": {"Date": "2026-01-01T00:00:00Z"}}]
    assert canonical_lifecycle_rules(server) == canonical_lifecycle_rules(spec_date_only)
    assert canonical_lifecycle_rules(server) == canonical_lifecycle_rules(spec_full)


def test_ilm_legacy_lowercase_shape_accepted():
    """v1 rc-export-shaped rules canonicalize the same way (migration aid)."""
    legacy = [{"id": "y", "prefix": "", "filter": {"prefix": ""}, "status": "Enabled"}]
    assert canonical_lifecycle_rules(legacy) == [{"status": "Enabled"}]


def test_inputs_not_mutated():
    rules = [{"ID": "keep", "Status": "Enabled", "Prefix": ""}]
    canonical_lifecycle_rules(rules)
    assert rules == [{"ID": "keep", "Status": "Enabled", "Prefix": ""}]
    doc = {"ID": "", "Statement": [{"Sid": "", "Action": ["b", "a"]}]}
    canonical_policy(doc)
    assert doc == {"ID": "", "Statement": [{"Sid": "", "Action": ["b", "a"]}]}
