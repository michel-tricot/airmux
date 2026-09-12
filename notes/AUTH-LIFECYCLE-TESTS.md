# Authentication lifecycle regression coverage

The regular acceptance job runs `tests/acceptance/scenarios/test_auth_lifecycles.py` against CLI-started control and data planes, a disposable Postgres database, and a local provider. Two competing requests are released together through a barrier, with bounded client and executor timeouts.

Invitation races cover repeated acceptance, acceptance versus revocation, and acceptance versus token reissue. The suite checks the winning transition, membership cardinality, old-token replay behavior, and absence of invitation secrets in member lists. Successful repeated acceptance is intentionally idempotent for the same account.

CLI races cover simultaneous approvals and simultaneous delivery polls. Exactly one approval wins and exactly one poll receives a credential. The credential authorizes a real request, appears only as metadata in listings, and becomes unusable after explicit revocation.

Password recovery races an old-password login against a password change. The old login may finish first or be denied, but its session must be unusable after both requests complete. The changing browser stays authenticated and a new-password login succeeds. Each scenario also verifies an unaffected inference request.

The control-plane integration suite parameterizes expired, revoked, reissued, and accepted invitation states across preview and redemption. Existing authentication tests cover expired CLI requests, wrong-account invitation attempts, closed signup, session expiration, and credential replacement. The ownership-invariant PR separately verifies concurrent initial signup, preventing bootstrap from being reopened after initialization.

Authentication quotas are increased only in lifecycle fixtures to accommodate deliberate multi-login setup. The dedicated throttling and resilience suites exercise restrictive quotas. No commercial provider or production account is used.
