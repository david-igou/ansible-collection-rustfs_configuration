# GNU General Public License v3.0+
# (see https://www.gnu.org/licenses/gpl-3.0.txt)
"""Canonicalization filters for comparing RustFS state.

The server does not return stable orderings: IAM policy Action/Resource
arrays come back in a different order on every call (stored as sets), and
ILM rule ids are server-generated (while `rc ilm rule import` REQUIRES an
id on every rule). Both sides of every comparison go through these filters
so ordering and volatile fields can never produce false drift.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import copy
import json


def rustfs_canonical_policy(doc):
    """Canonicalize an IAM policy document for comparison.

    The server echoes every policy back with empty boilerplate fields it
    injects on store: a document-level ``ID: ""`` and, on each statement,
    ``Sid: ""`` and ``Condition: {}``. A hand-authored document that omits
    these (the natural way to write one) would otherwise never equal the
    server's echo, re-applying ``policy:<name>:update`` on every run. Both
    sides go through this filter, so the empties are dropped symmetrically
    and a from-scratch policy converges to steady state.
    """
    d = copy.deepcopy(doc)
    statements = d.get("Statement", [])
    for s in statements:
        for k in ("Action", "Resource"):
            if isinstance(s.get(k), list):
                s[k] = sorted(s[k])
        if s.get("Condition") == {}:
            del s["Condition"]
        if s.get("Sid") == "":
            del s["Sid"]
    d["Statement"] = sorted(statements, key=lambda s: json.dumps(s, sort_keys=True))
    if d.get("ID") == "":
        del d["ID"]
    return d


def rustfs_canonical_ilm(rules):
    """Canonicalize an ILM rule list for comparison.

    Strips server-generated rule ids (lowercase ``id`` — the only casing
    rc 0.1.x emits, pinned by unit fixture) and orders rules
    deterministically.

    Also drops empty scoping: an empty top-level ``prefix: ""`` or an empty
    ``filter`` (``{}`` or ``{"prefix": ""}``) means "the whole bucket", which
    the server omits entirely on export. A whole-bucket rule written with an
    explicit empty prefix/filter would otherwise never equal the server's
    export, re-importing ``lifecycle:import`` on every run. (A NON-empty
    ``filter`` is left as-is; the server honours only a top-level ``prefix``,
    so a nested non-empty filter surfaces as persistent drift rather than
    being silently masked — see docs/server-quirks.md.)
    """
    rs = copy.deepcopy(rules)
    for r in rs:
        r.pop("id", None)
        if r.get("prefix") == "":
            del r["prefix"]
        f = r.get("filter")
        if isinstance(f, dict):
            if f.get("prefix") == "":
                del f["prefix"]
            if not f:
                del r["filter"]
    return sorted(rs, key=lambda r: json.dumps(r, sort_keys=True))


class FilterModule(object):
    """RustFS canonicalization filters."""

    def filters(self):
        return {
            "rustfs_canonical_policy": rustfs_canonical_policy,
            "rustfs_canonical_ilm": rustfs_canonical_ilm,
        }
