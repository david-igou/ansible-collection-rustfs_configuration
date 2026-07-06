# GNU General Public License v3.0+
"""Unit tests for the RustFS canonicalization filters."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import copy

from ansible_collections.david_igou.rustfs_configuration.plugins.filter.rustfs import (
    rustfs_canonical_ilm,
    rustfs_canonical_policy,
)

POLICY = {
    "ID": "",
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ListAndDescribeBucket",
            "Effect": "Allow",
            "Condition": {},
            "Action": ["s3:ListBucketMultipartUploads", "s3:GetBucketLocation", "s3:ListBucket"],
            "Resource": ["arn:aws:s3:::quay"],
        },
        {
            "Sid": "ReadWriteDeleteObjects",
            "Effect": "Allow",
            "Condition": {},
            "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
            "Resource": ["arn:aws:s3:::quay/*"],
        },
    ],
}


# A from-scratch document as a user naturally writes it: no document-level
# ID, no per-statement Sid/Condition boilerplate.
POLICY_NO_SID_DESIRED = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": ["s3:GetObject", "s3:ListBucket"],
            "Resource": ["arn:aws:s3:::app-data", "arn:aws:s3:::app-data/*"],
        }
    ],
}

# The SAME policy as the server echoes it back (verified live on
# 1.0.0-beta.8): empty ID/Sid/Condition injected, arrays reordered.
POLICY_SERVER_ECHO = {
    "ID": "",
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "",
            "Effect": "Allow",
            "Condition": {},
            "Action": ["s3:ListBucket", "s3:GetObject"],
            "Resource": ["arn:aws:s3:::app-data/*", "arn:aws:s3:::app-data"],
        }
    ],
}


def _shuffled_policy():
    """The same policy as the server returns it on another call: arrays and
    statements reordered (the server stores sets)."""
    p = copy.deepcopy(POLICY)
    p["Statement"] = [p["Statement"][1], p["Statement"][0]]
    for s in p["Statement"]:
        s["Action"] = list(reversed(s["Action"]))
    return p


def test_policy_ordering_permutations_are_equal():
    assert rustfs_canonical_policy(POLICY) == rustfs_canonical_policy(_shuffled_policy())


def test_policy_empty_condition_and_id_are_dropped():
    canon = rustfs_canonical_policy(POLICY)
    assert "ID" not in canon
    assert all("Condition" not in s for s in canon["Statement"])


def test_policy_nonempty_condition_passes_through():
    p = copy.deepcopy(POLICY)
    cond = {"StringEquals": {"aws:username": "quay"}}
    p["Statement"][0]["Condition"] = cond
    canon = rustfs_canonical_policy(p)
    assert any(s.get("Condition") == cond for s in canon["Statement"])


def test_policy_input_is_not_mutated():
    p = copy.deepcopy(POLICY)
    rustfs_canonical_policy(p)
    assert p == POLICY


def test_policy_empty_sid_is_dropped():
    canon = rustfs_canonical_policy(POLICY_NO_SID_DESIRED)
    assert all("Sid" not in s for s in canon["Statement"])


def test_policy_from_scratch_matches_server_echo():
    """The natural hand-authored document (no ID/Sid/Condition boilerplate)
    must equal the server's echo, which injects empty ID/Sid/Condition — else
    the policy re-applies `update` on every run. Regression for the empty-Sid
    idempotence trap (the server adds Sid: "" but the filter used to keep it).
    """
    assert rustfs_canonical_policy(POLICY_NO_SID_DESIRED) == rustfs_canonical_policy(
        POLICY_SERVER_ECHO
    )


def test_policy_nonempty_sid_passes_through():
    canon = rustfs_canonical_policy(POLICY)
    assert any(s.get("Sid") == "ListAndDescribeBucket" for s in canon["Statement"])


ILM_RULES = [
    {
        "id": "281c0dcb-6493-4ad5-abbd-5277e3558ada",
        "status": "Enabled",
        "prefix": "routeros/",
        "tags": {"tier": "daily"},
        "noncurrentVersionExpiration": {"noncurrentDays": 14},
    },
    {
        "id": "873e3dd0-9249-4bed-b714-f4838fcd7678",
        "status": "Enabled",
        "prefix": "routeros/",
        "noncurrentVersionExpiration": {"noncurrentDays": 90},
    },
]


def test_ilm_ids_are_ignored_in_comparison():
    regenerated = copy.deepcopy(ILM_RULES)
    for r in regenerated:
        r["id"] = "ffffffff-0000-0000-0000-000000000000"
    assert rustfs_canonical_ilm(ILM_RULES) == rustfs_canonical_ilm(regenerated)


def test_ilm_ordering_is_deterministic():
    assert rustfs_canonical_ilm(ILM_RULES) == rustfs_canonical_ilm(list(reversed(ILM_RULES)))


def test_ilm_id_casing_fixture():
    """Pin the export id key casing: rc 0.1.x emits lowercase `id` only.

    If a future rc/server pair starts emitting `ID`, this fixture forces a
    deliberate decision instead of silent perpetual drift: an uppercase-ID
    rule is NOT stripped today.
    """
    upper = [{"ID": "abc", "status": "Enabled", "prefix": "x/"}]
    assert rustfs_canonical_ilm(upper)[0].get("ID") == "abc"


def test_ilm_rule_content_differences_are_detected():
    changed = copy.deepcopy(ILM_RULES)
    changed[0]["noncurrentVersionExpiration"]["noncurrentDays"] = 7
    assert rustfs_canonical_ilm(ILM_RULES) != rustfs_canonical_ilm(changed)


def test_ilm_empty_scoping_matches_server_drop():
    """A whole-bucket rule written with an explicit empty prefix/filter must
    equal the server's export, which drops empty scoping entirely — else the
    rule re-imports every run. Regression for the empty-filter idempotence
    trap (verified live: import `filter: {prefix: ""}` -> export has no
    filter). Covers all three empty shapes a user might write.
    """
    server_export = [{"id": "srv-gen-id", "status": "Enabled", "expiration": {"days": 30}}]
    for empty_scoped in (
        [{"id": "a", "status": "Enabled", "prefix": "", "expiration": {"days": 30}}],
        [{"id": "a", "status": "Enabled", "filter": {"prefix": ""}, "expiration": {"days": 30}}],
        [{"id": "a", "status": "Enabled", "filter": {}, "expiration": {"days": 30}}],
    ):
        assert rustfs_canonical_ilm(empty_scoped) == rustfs_canonical_ilm(server_export)


def test_ilm_nonempty_prefix_is_preserved():
    """A real top-level prefix must survive canonicalization (the server
    honours it), so scoped rules still compare correctly."""
    scoped = [{"id": "a", "status": "Enabled", "prefix": "logs/", "expiration": {"days": 15}}]
    whole = [{"id": "b", "status": "Enabled", "expiration": {"days": 15}}]
    assert rustfs_canonical_ilm(scoped) != rustfs_canonical_ilm(whole)
    assert rustfs_canonical_ilm(scoped)[0].get("prefix") == "logs/"


def test_ilm_current_object_expiration_is_preserved():
    """The documented current-object `expiration: {days: N}` shape (verified
    to round-trip through `rc ilm rule export` unchanged) must pass through
    canonicalization intact — only the id is stripped — so it compares equal
    to the server's export and stays idempotent. Distinct from the
    noncurrent-version shape."""
    desired = [{"id": "expire-objects-30d", "status": "Enabled", "expiration": {"days": 30}}]
    server_export = [{"id": "srv-gen", "status": "Enabled", "expiration": {"days": 30}}]
    assert rustfs_canonical_ilm(desired) == rustfs_canonical_ilm(server_export)
    # and it is genuinely different from a noncurrent-version rule
    noncurrent = [{"id": "x", "status": "Enabled", "noncurrentVersionExpiration": {"noncurrentDays": 30}}]
    assert rustfs_canonical_ilm(desired) != rustfs_canonical_ilm(noncurrent)
