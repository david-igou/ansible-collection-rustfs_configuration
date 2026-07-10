# -*- coding: utf-8 -*-

# GNU General Public License v3.0+
# (see https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type


class ModuleDocFragment(object):
    # Connection options shared by every rustfs_* module.
    DOCUMENTATION = r"""
options:
  endpoint:
    description:
      - URL of the RustFS server, for example V(https://nas.example.net:20292).
      - Plain V(http://) endpoints are accepted for dev/test instances.
    type: str
    required: true
  access_key:
    description:
      - Access key the module authenticates with.
      - For admin-plane modules this must be an admin/root credential.
    type: str
    required: true
  secret_key:
    description:
      - Secret key paired with O(access_key).
    type: str
    required: true
  region:
    description:
      - Region used for AWS SigV4 request signing.
      - RustFS accepts the default on single-node deployments; change it only
        if the server was deployed with a different region identity.
    type: str
    default: us-east-1
  validate_certs:
    description:
      - Whether to validate TLS certificates of the endpoint.
      - Only affects V(https://) endpoints.
    type: bool
    default: true
  ca_bundle:
    description:
      - Path to a CA bundle used to verify the endpoint's TLS certificate,
        for private-CA deployments.
    type: path
  retries:
    description:
      - Total attempts for each API call.
      - Only transport-level failures (connection refused/reset, timeouts,
        HTTP 502/503/504) are retried - the RustFS admin API is known to
        refuse connections in bursts while the S3 data path stays healthy.
      - Permanent errors (authentication, not-found, conflict, validation)
        fail immediately.
    type: int
    default: 8
  retry_delay:
    description:
      - Seconds to sleep between retry attempts.
    type: int
    default: 3
requirements:
  - botocore
notes:
  - All requests are signed with AWS SigV4 (service C(s3)) - both the S3
    data plane and the RustFS admin REST API under C(/rustfs/admin/v3).
  - Every connection option can also be provided via environment variables
    of the module's process - E(RUSTFS_ENDPOINT), E(RUSTFS_ACCESS_KEY),
    E(RUSTFS_SECRET_KEY), E(RUSTFS_REGION), E(RUSTFS_VALIDATE_CERTS),
    E(RUSTFS_CA_BUNDLE), E(RUSTFS_RETRIES), E(RUSTFS_RETRY_DELAY) - for
    example through the C(environment) keyword on a block or play.
"""
