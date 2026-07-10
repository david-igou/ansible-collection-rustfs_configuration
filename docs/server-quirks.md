# RustFS server quirks (empirical, 1.0.0-beta.8)

Everything below was established by exercising a live `rustfs/rustfs:1.0.0-beta.8`
server — first through the `rc` CLI (v1 of this collection), then directly
against the S3 and admin REST APIs (the 2.x modules). It is the knowledge the
collection's design is built on; re-verify the marked items after every server
image bump (run your drift job right after any live server upgrade).

Since 2.0.0 the collection speaks the APIs directly (botocore for the S3
plane; SigV4-signed plain-JSON for `/rustfs/admin/v3/*`), so rc-specific
quirks are gone and some "server" quirks turned out to be rc artifacts —
kept below under *Overturned* because they explain v1 design fossils.

## Quirks the modules code around

| Quirk | Where it lands |
|---|---|
| `CreateBucket` on an EXISTING bucket returns false success | `bucket` decides existence by read (HeadBucket), never by the create call |
| IAM policy `Action`/`Resource` arrays return in a different order on every call (stored as sets) | `canonical_policy` (module_utils, shared with the `canonical_policy` filter) on both sides of every comparison |
| Storing a policy injects empty boilerplate into the echo: document-level `ID: ""` and, per statement, `Sid: ""` and `Condition: {}` | `canonical_policy` drops all three empties on both sides, so a from-scratch document (written without them) stays idempotent |
| `GET /info-canned-policy` answers a metadata WRAPPER `{policy_name, policy: <doc>, create_date, update_date}` (verified live) | `RustfsAdminClient.get_policy` unwraps to the document |
| A MISSING canned policy answers HTTP **500 InternalError** ("policy does not exist"), not 404 (verified live in molecule) | every admin `get_*` treats a permanent error carrying "does not exist" as not-found; genuine 500s still raise |
| ILM read DROPS empty scoping — a whole-bucket rule stored with `Prefix: ""` comes back with no Prefix/Filter at all | `canonical_lifecycle_rules` treats empty Prefix/Filter as absent on both sides |
| ILM put is a FULL REPLACE of the bucket's rules | `bucket_lifecycle` reconciles the whole ruleset — no per-rule editing; the spec is the entire configuration |
| `DELETE /remove-canned-policy` while the policy is attached → HTTP 500 | `policy` `state: absent` maps it to a clear detach-first error (the role never deletes anyway) |
| `PUT /set-user-or-group-policy` REPLACES the whole attachment set (not additive), and **no detach endpoint exists** (rc's detach is a stub returning UnsupportedFeature) | `policy_attachment` reads current and writes union (`exclusive: false`, role behavior — extras survive) or the exact list (`exclusive: true` — which IS detach on this server) |
| `PUT /add-user` on an existing access key rotates the secret in place (attachments survive) | `user` never re-PUTs an existing user unless `update_secret: true` |
| S3 credential validation: `ListBuckets` with a wrong secret → `SignatureDoesNotMatch` / unknown key → `InvalidAccessKeyId`; `AccessDenied` means the pair is VALID but unauthorized | `credential_info` separates `authenticated` from `authorized` (rc lumped data-path AccessDenied in with retryable network errors) |
| Admin API (`/rustfs/admin/v3/*`) refuses connections in bursts while the S3 data path stays healthy | every call retries transport-level failures only (connection refused/reset, timeouts, HTTP 502/503/504), `retries`/`retry_delay` params |
| `create-service-account` requires the `expiration` JSON key to be PRESENT (null when unset) | `RustfsAdminClient.create_service_account` always emits it |
| No service-account update endpoint exists in beta-8 | `service_account` never modifies an existing account (documented: remove + recreate) |
| A request signed by a DISABLED access key answers `InvalidRequest`/`ErrAccessKeyDisabled` (found live) | `credential_info` reports it as a verdict — `authenticated: true`, `usable: false`, detail carries the code — instead of erroring |
| **Group admin API is stubbed server-side**: `POST /groups` answers HTTP 501 NotImplemented on beta-8 (found live by the molecule `modules` scenario) even though the endpoints exist in the rc client | `group`/`group_info` work against a future server build; the molecule group walk tolerates exactly this failure and re-arms automatically when a build implements groups |

## Admin API contract (established from rc v0.1.25 source, verified live)

- Base path `/rustfs/admin/v3`; bodies plain JSON, camelCase keys —
  **no MinIO-style payload encryption**.
- Auth: AWS SigV4 in headers, service name `s3`, region from config
  (default `us-east-1`). Required headers: `host`,
  `x-amz-content-sha256` (hex SHA256 of the exact body bytes; empty-body
  constant on GET/DELETE), `content-type: application/json` only when a
  body is present.
- Error mapping: 404 not-found, 401/403 auth, 409 conflict, 400 bad
  request — but see the 500-not-found quirk above.
- `list-users` returns a map `accessKey → {status, policyName, memberOf}`;
  `policyName` is a comma-joined string.

## Overturned in 2.0.0 (rc artifacts, not server behavior)

| v1 belief | What direct-API testing showed |
|---|---|
| "ILM honours ONLY a top-level `prefix`; a nested `filter` is silently dropped on export" | A `Filter: {Prefix: ...}` **survives a direct S3 put/get round-trip** (verified live). The drop was in rc's JSON serialization. Whether the expiry scanner honours Filter at execution time remains unverified — top-level `Prefix` is still the recommended shape. |
| "`ilm rule import` REQUIRES an `id` on every rule" | rc-level validation. The S3 put accepts id-less rules; `bucket_lifecycle` generates deterministic content-derived IDs anyway so comparisons and server state stay stable. |
| "Versioned buckets are undeletable" | `rc bucket remove --force` was unimplemented client-side (exit 6). An EMPTY versioned bucket deletes fine over direct S3 `DeleteBucket` (verified live by the molecule `modules` walk); non-empty buckets fail as usual. |
| "clear-all lifecycle semantics unverified" | `DeleteBucketLifecycle` works (verified live) — `bucket_lifecycle` `state: absent` has defined semantics. The ROLE still rejects `rules: []` (deletion safety). |
| rc exit-code taxonomy (3 = the only retryable) as the retry key | Replaced by HTTP-level classification in module_utils; no string/exit-code matching anywhere. |

## Known unknowns (re-verify on every server pin bump)

- **404-vs-500 not-found shapes**: which admin endpoints answer 404 vs 500
  "does not exist" is empirical per endpoint on beta-8. The `_is_not_found`
  helper covers both; a future server normalizing to 404 changes nothing.
- **`/info-canned-policy` envelope**: the `{policy_name, policy, ...}`
  wrapper is pinned by unit fixture; a future server returning the bare
  document also works (the unwrap is conditional).
- **ILM Filter honoured at scan time?** Round-trips cleanly (above), but
  whether the expiry scanner applies a nested Filter is untested — scope
  with top-level `Prefix` until verified.
- **Buckets are directories under `/data`** (single-node layout): the molecule
  verify uses `podman exec rustfs-server ls /data` as an independent
  server-side check. This coupling is the FIRST suspect if a server image
  bump breaks verify.
