# GNU General Public License v3.0+
"""Unit tests for bucket_lifecycle's deterministic rule-ID generation."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

from ansible_collections.david_igou.rustfs.plugins.modules.bucket_lifecycle import (
    with_rule_ids,
)

RULE = {"Status": "Enabled", "Prefix": "tmp/", "Expiration": {"Days": 7}}


def test_generated_id_is_deterministic():
    first = with_rule_ids([dict(RULE)])[0]["ID"]
    second = with_rule_ids([dict(RULE)])[0]["ID"]
    assert first == second
    assert first.startswith("ansible-") and len(first) == len("ansible-") + 16


def test_supplied_id_is_preserved():
    rule = dict(RULE, ID="mine")
    assert with_rule_ids([rule])[0]["ID"] == "mine"


def test_id_derives_from_rule_content():
    changed = dict(RULE, Expiration={"Days": 14})
    assert with_rule_ids([dict(RULE)])[0]["ID"] != with_rule_ids([changed])[0]["ID"]


def test_id_stable_across_array_ordering():
    a = {"Status": "Enabled", "Filter": {"Prefix": "x/"}, "Expiration": {"Days": 3}}
    # Same rule content in different key insertion order canonicalizes equal.
    b = {"Expiration": {"Days": 3}, "Filter": {"Prefix": "x/"}, "Status": "Enabled"}
    assert with_rule_ids([a])[0]["ID"] == with_rule_ids([b])[0]["ID"]


def test_input_rules_not_mutated():
    rule = dict(RULE)
    with_rule_ids([rule])
    assert "ID" not in rule
