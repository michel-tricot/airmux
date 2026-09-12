# Control-plane throttling

The control plane applies a local token bucket before database-backed authentication, using the client address supplied by the ASGI server. It does not parse forwarding headers. Configure the server to trust only the actual reverse proxy; never trust arbitrary client-supplied forwarding headers.

Each request consumes an allowance for its traffic group. Authentication, CLI traffic, ordinary API traffic, and operational synchronization have separate budgets. Browser sessions also share a principal allowance; management keys have a credential allowance after successful authentication. Password attempts additionally consume an IP-and-normalized-email allowance regardless of whether the account exists. Health probes and static assets are outside API quotas.

Settings live under `control_plane.throttling`. Each group accepts `burst` and `per_second`. Defaults permit 120 ordinary requests in a burst with 20 tokens refilled per second, five authentication attempts with one token every six seconds, ten CLI requests in a burst with two tokens refilled per second, and 1000 operational requests with 100 tokens per second. Account buckets permit five attempts with one token every twelve seconds. Tune operational limits for the number of data planes and organizations fetched at startup.

Exhausted quotas return 429 with `Retry-After`. Local backend capacity and password-work capacity exhaustion return 503 with `Retry-After`. Requests are rejected immediately; the limiter never sleeps or holds a database transaction while waiting for quota. Responses carry `Cache-Control: no-store`.

## Backend contract

`ThrottleBackend.consume(key, limit)` is asynchronous and atomically consumes one token or returns a denial with positive retry timing. A rejected attempt must not consume a token. Keys contain a traffic namespace and hashed identity; raw credentials and emails never enter backend keys. The backend owns its clock and expiry. Distributed implementations should use a server-side atomic operation and a shared clock. A storage failure must produce a capacity denial or propagate an operational error, never silently permit traffic.

`create_app(throttle_backend=...)` injects an implementation. Route classification, identity selection, configuration, and HTTP response rendering do not belong in the backend. The default implementation uses a monotonic clock and bounded storage, removes fully refilled buckets, and rejects new identities when storage is full instead of evicting active limits. Limits are independent per process and reset on restart. A shared backend is needed for a deployment-wide quota.

## Password work

Password hashing and verification run in a dedicated thread pool with two workers and eight queued operations by default. Configure `password_workers` and `password_queue` within the throttling settings. Cancellation does not free capacity until the underlying work has actually finished. Worker threads receive an empty context so they cannot inherit the ambient database transaction. Database changes remain on the event loop. Shutdown drains running password work.

These limits bound local load; they do not replace upstream protection from distributed denial of service.
