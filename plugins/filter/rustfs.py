# GNU General Public License v3.0+
# (see https://www.gnu.org/licenses/gpl-3.0.txt)
"""Canonicalization filters for comparing RustFS state.

Thin public wrappers: the single source of truth lives in
module_utils/canonical.py, shared with the collection's modules so
filter and module comparisons can never diverge.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

from ansible_collections.david_igou.rustfs.plugins.module_utils import canonical


def canonical_policy(doc):
    """Canonicalize an IAM policy document for comparison."""
    return canonical.canonical_policy(doc)


def canonical_ilm(rules):
    """Canonicalize an ILM rule list for comparison.

    Accepts both the S3 API shape (PascalCase - what the collection's
    modules speak) and the legacy rc-export shape (lowercase keys).
    """
    return canonical.canonical_lifecycle_rules(rules)


class FilterModule(object):
    """RustFS canonicalization filters."""

    def filters(self):
        return {
            "canonical_policy": canonical_policy,
            "canonical_ilm": canonical_ilm,
        }
