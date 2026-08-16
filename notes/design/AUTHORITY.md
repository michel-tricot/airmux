# Control-plane authority

This document is the source of truth for control-plane authorization. Inference keys are a data-plane
credential and are deliberately outside this model.

## Decision model

Every protected request resolves four facts:

1. A principal, either a human or a service account
2. The principal's standing authority from current roles
3. A credential ceiling, which can only remove permissions
4. A target at the instance, organization, or workspace boundary

A request is allowed only when all three checks pass:

```text
credential boundary covers target
and permission is in credential ceiling
and permission is in standing authority for target
```

Standing authority is evaluated on every request. Removing a membership or changing a role takes
effect without rewriting or redistributing keys. Restoring the role can make an otherwise live key
usable again, because a key records a ceiling rather than a copy of the role grant.

## Tenant boundaries

Boundaries form a strict containment hierarchy:

```text
instance
└── organization
    └── workspace
```

- An instance boundary covers the instance and every organization and workspace below it
- An organization boundary covers that organization and its workspaces, never the instance or another organization
- A workspace boundary covers only that workspace, never its organization or a sibling workspace

`Target` is the validated representation. An instance target has no tenant ids, an organization
target has only `org_id`, and a workspace target has both `org_id` and `workspace_id`.

Routes declare one permission and one target resolver. The declaration drives enforcement and the
OpenAPI description, and API hygiene tests reject an unclassified route.

## Roles

Roles grant standing authority. Grants are explicit sets, so adding a permission to the catalog does
not silently grant it to an existing role. Instance grants combine with organization grants, and
organization grants combine with workspace grants for a target below them.

### Instance roles

| Role | Grant |
|---|---|
| `owner` | Every control-plane permission |
| `auditor` | Read-only organization, principal, membership, workspace, catalog, credential, key, bundle, usage, data-plane, and audit access |
| `data_plane` | `bundles.read`, `usage.ingest`, and `data-planes.heartbeat` only |

Only humans can hold `owner` or `auditor`, and only a service account can hold `data_plane`. The
first human signup becomes the instance owner. The `airllmcp owner` command is the local recovery
path for promoting an existing human account.

### Organization roles

| Role | Grant |
|---|---|
| `owner` | Organization lifecycle, members, workspaces, provider credentials, inference keys, bundles, usage, audit, and access keys |
| `admin` | The owner grant except organization deletion and owner assignment |
| `member` | Read the organization and catalog, list workspaces, and create a workspace |
| `data_plane` | `bundles.read`, `usage.ingest`, and `data-planes.heartbeat` only |

An organization must retain at least one owner. An admin cannot assign, change, or remove an owner.
Removing an organization membership cascades its workspace memberships.

### Workspace roles

| Role | Grant |
|---|---|
| `admin` | Workspace update and deletion, membership management, provider credentials, inference keys, usage, and workspace access keys |
| `member` | Workspace and membership reads, catalog and provider-credential reads, inference-key management, and usage reads |
| `viewer` | The member read surface without inference-key management |

An organization member who creates a workspace becomes its first workspace admin. An instance owner
can create a workspace without joining it because instance authority already covers the target.

## Access keys

`AccessKey` is the only control-plane key resource. Every key:

- Uses the `sk-cp-` prefix
- Authenticates one principal
- Has exactly one tenant boundary
- Stores a non-empty explicit permission ceiling
- May expire
- May name a parent access key
- Stores only a token hash and display prefix
- Returns the full token once, when minted

There is no null or omitted permission list meaning "everything". Existing keys therefore never
gain a newly introduced permission. A key's effective authority is always the intersection of its
stored ceiling and the principal's current roles.

Sessions use the same authority evaluator. A session has no key boundary and an all-permissions
ceiling, but current roles still determine what the human can do at the selected target.

### Issuance and delegation

Creating a key requires `access-keys.issue` at the requested target. The requested permissions must
be contained by both the acting principal's standing authority and the receiving principal's
standing authority.

When an access key creates another access key, the child is a delegated key and must satisfy extra
attenuation rules:

- Its permission ceiling is a strict subset of the issuer's ceiling
- It cannot carry `access-keys.issue`
- It cannot outlive the issuer
- Its target must be covered by the issuer's boundary
- It records the issuer as its parent

Verification walks the parent chain. A missing, expired, or revoked ancestor invalidates every
descendant. Revoking a key records one timestamp and recursively revokes its descendants.

CLI login may present its current access key as the bearer on the one-time delivery request. The
server verifies that token, resolves its unique key id, and retires exactly that key and its
descendants only when its principal and target match the approved login. Labels remain display
metadata and never identify a credential. A login with no valid existing bearer revokes nothing.

### Target selection

An organization-bound or workspace-bound key supplies its own organization context. `X-Org-Id` may
confirm that organization but cannot switch it. An instance-bound key or browser session uses `X-Org-Id`
on organization routes. Routes whose resource identifies the organization resolve their target from
that resource instead.

The access-key collection accepts explicit `org_id` and `workspace_id` targets. With no explicit
target, a key inherits its own boundary and a session targets the instance.

Self-service identity responses are boundary-aware. An organization-bound or workspace-bound key
can inspect its human principal but cannot use `/auth/me` or `/enroll` to enumerate the principal's
other organizations. Founding a personal organization requires a browser session.

Workspace-bound usage reads select that workspace when the query omits one and reject a sibling
workspace explicitly, so a tenant boundary cannot be bypassed by leaving the filter blank.

## Data-plane authority

A managed data plane authenticates with an ordinary access key whose principal is a service account
holding a `data_plane` role. The default is the instance role and an instance-bound key, which makes
the data plane global. A deployment dedicated to one organization uses the organization role and an
organization-bound key instead. In both cases the key ceiling must be exactly:

```text
bundles.read
usage.ingest
data-planes.heartbeat
```

Those permissions match the only control-plane actions the data plane performs:

- Poll the latest signed bundle globally or for the organization selected by its boundary or configuration
- Ingest usage events, with every event checked against its workspace target
- Heartbeat, retaining a null organization for a global instance or the key's organization for a dedicated instance

The public OSS quickstart endpoint does not mint authority. It accepts an already minted live key
only while no data plane has registered, verifies the service-account role, supported boundary, and
exact permission set, then writes that token to the shared data-plane key file. The CLI keeps the
simple first-run path by creating the global service account, role, and limited key before calling it.

## Adding authority

Adding a protected operation requires all of the following:

1. Add a `Permission` only when no existing permission describes the same authority
2. Add it explicitly to the roles that should receive it
3. Declare the permission and target resolver on the route
4. Test the allowed role, a lower role, a narrower boundary, and a narrower key ceiling
5. Regenerate OpenAPI and clients

Do not infer permissions from HTTP methods, route names, key labels, or JSON field overlap. The
permission catalog, role grants, target hierarchy, and access-key ceiling are the complete model.
