# GNU General Public License v3.0+
"""Unit tests for the RustFS canonicalization filters."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import copy

from ansible_collections.david_igou.rustfs.plugins.filter.rustfs import (
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
