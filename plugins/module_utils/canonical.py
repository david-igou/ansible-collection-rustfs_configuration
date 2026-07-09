# -*- coding: utf-8 -*-

# GNU General Public License v3.0+
# (see https://www.gnu.org/licenses/gpl-3.0.txt)
"""Canonicalization for comparing RustFS state (single source of truth).

The server does not return stable representations: IAM policy
Action/Resource arrays come back in a different order on every call
(stored as sets), storing a policy injects empty boilerplate into the
echo, lifecycle rule ids are server-relevant but comparison-irrelevant,
and empty lifecycle scoping is dropped on read. Both sides of every
comparison - in the modules and in the public filter plugins - go
through these functions so none of that can produce false drift.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import copy
import json
from datetime import date, datetime, timezone


def canonical_policy(doc):
    """Canonicalize an IAM policy document for comparison.

    The server echoes every policy back with empty boilerplate fields it
    injects on store: a document-level ``ID: ""`` and, on each statement,
    ``Sid: ""`` and ``Condition: {}``. A hand-authored document that omits
    these (the natural way to write one) would otherwise never equal the
    server's echo. Action/Resource arrays are sorted (the server stores
    them as sets), and statements are ordered deterministically.
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


def _canonical_date(value):
    """Normalize a lifecycle Date to ``YYYY-MM-DDTHH:MM:SSZ``.

    botocore returns parsed datetime objects on read while specs carry
    strings - both sides must land on one representation.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return value
    else:
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonicalize_dates(node):
    if isinstance(node, dict):
        return dict(
            (k, _canonical_date(v) if k == "Date" else _canonicalize_dates(v))
            for k, v in node.items()
        )
    if isinstance(node, list):
        return [_canonicalize_dates(item) for item in node]
    return node


def canonical_lifecycle_rules(rules):
    """Canonicalize a lifecycle (ILM) rule list for comparison.

    Strips rule ids (server-relevant, comparison-irrelevant), absorbs
    empty scoping (an empty ``Prefix``/``Filter`` means "whole bucket" and
    the server omits it entirely on read), normalizes Date fields, and
    orders rules deterministically. Accepts both the S3 API shape
    (``ID``/``Prefix``/``Filter`` - what the modules speak) and the legacy
    rc-export shape (lowercase keys), so v1 specs compare sanely during
    migration.
    """
    rs = _canonicalize_dates(copy.deepcopy(rules))
    for r in rs:
        for id_key in ("ID", "id"):
            r.pop(id_key, None)
        for prefix_key in ("Prefix", "prefix"):
            if r.get(prefix_key) == "":
                del r[prefix_key]
        for filter_key in ("Filter", "filter"):
            f = r.get(filter_key)
            if isinstance(f, dict):
                for prefix_key in ("Prefix", "prefix"):
                    if f.get(prefix_key) == "":
                        del f[prefix_key]
                if not f:
                    del r[filter_key]
    return sorted(rs, key=lambda r: json.dumps(r, sort_keys=True, default=str))
