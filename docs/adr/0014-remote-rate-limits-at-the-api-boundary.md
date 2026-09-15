# ADR 0014: Remote rate limits live at the API boundary

## Status

Accepted — 2026-09-15.

## Context

The desktop application binds the backend to loopback and already controls who can reach it. A
team deployment exposes the same API to a network: login and OAuth endpoints are unauthenticated,
while generation, agent and media-processing endpoints can spend provider budget or occupy scarce
workers. Authentication and job admission answer different questions and do not bound request rate.

Adding limits inside each route would duplicate identity, policy and response semantics across the
application. A third-party service would also add an operational dependency that the current
single-process deployment does not need.

## Decision

1. `app/core/rate_limit.py` is the single API-boundary module. It classifies three policy groups:
   authentication, OAuth and billable/expensive mutations, and returns a standard 429 response with
   `Retry-After` and rate-limit headers.
2. Automatic mode is disabled for the packaged desktop and loopback hosts, and enabled when the
   backend listens on a remote address. `MOSAEL_RATE_LIMIT_ENABLED` can explicitly override this.
3. Authentication and OAuth use the direct client address. Billable work uses a hash of the Bearer
   session so users behind one NAT do not consume each other's quota, plus a wider client-address
   safety bucket so rotating invalid tokens cannot bypass the boundary.
4. `X-Forwarded-For` is ignored unless the direct peer appears in
   `MOSAEL_RATE_LIMIT_TRUSTED_PROXIES`; accepting it from everyone would let a caller choose a new
   identity on every request.
5. Windows live in process memory. This matches the documented one-process backend. Before adding a
   second backend process, the window store must move to a shared gateway/store; the constraint is
   recorded in `docs/PROCESS_STATE.md`.

## Consequences

- Remote deployments receive useful protection without slowing or surprising local desktop work.
- Routes do not import limiter concepts and new policy groups have one implementation seam.
- Limits reset on restart, which is acceptable for abuse control rather than accounting.
- Operators can tune the three per-minute limits independently with
  `MOSAEL_RATE_LIMIT_AUTH_PER_MINUTE`, `MOSAEL_RATE_LIMIT_OAUTH_PER_MINUTE` and
  `MOSAEL_RATE_LIMIT_BILLABLE_PER_MINUTE`.
