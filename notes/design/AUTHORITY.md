# Control-plane authority

This document is the source of truth for control-plane authorization. Inference keys are data-plane
credentials and are deliberately outside this model.

## Decision model

Every protected request resolves four facts:

1. A principal, either a human or a service account
2. The principal's standing grants from current roles and memberships
3. The authenticating credential's scope and permission ceiling
4. The requested permission and target scope

A request is allowed only when all three conditions hold:

```text
credential scope covers target scope
and requested permission is in the credential ceiling
and a current standing grant covers the target and permission
```

`authz.decide` is the pure policy kernel. `authority` loads standing grants and owns conditional
decisions such as role assignment and delegated-key issuance. Routes do not interpret roles,
credential claims, or tenant identifiers. Each route declares one permission and one scope resolver,
and API hygiene tests reject unclassified routes or permission checks without a scope.

Standing grants are evaluated on every request. Removing a membership or changing a role takes
effect without rewriting keys. Restoring the role can make an otherwise live key usable again,
because a key records a ceiling rather than a copy of its principal's roles.

## Scope hierarchy

Scopes form a strict containment hierarchy:

```text
instance
└── organization
    └── workspace
```

- Instance scope covers the instance and every organization and workspace
- Organization scope covers that organization and its workspaces, never the instance or another organization
- Workspace scope covers only that workspace, never its organization or a sibling workspace

`Scope` is the validated representation. Instance scope has no tenant identifiers, organization
scope has only `org_id`, and workspace scope has both `org_id` and `workspace_id`.

Management URLs state their target explicitly:

```text
/api/v1/instance/...
/api/v1/orgs/{org_id}/...
/api/v1/orgs/{org_id}/workspaces/{workspace_ref}/...
```

There is no tenant-selection header. A path, a resolved resource, or the data-plane credential
itself supplies the target, so credentials cannot redirect a request by changing ambient context.

## Roles and standing grants

Roles grant explicit permission sets. Adding a permission to the catalog does not silently grant it
to existing roles. An instance grant applies to every descendant target, an organization grant
applies to that organization's workspaces, and a workspace grant applies only to that workspace.

### Instance roles

| Role | Grant |
|---|---|
| `owner` | Every control-plane permission |
| `auditor` | Read-only organization, principal, membership, workspace, catalog, credential, key, bundle, usage, data-plane, and audit access |
| `data_plane` | `bundles.read`, `usage.ingest`, and `data-planes.heartbeat` only |

The first human signup becomes the instance owner. The `airllmcp owner` command is the local recovery
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

Human and service-account principals use the same role system. A service account may hold any role;
authorization depends on its resulting standing grants, not its principal kind or a special role name.

## Access keys

`AccessKey` is the only control-plane key resource. Every key:

- Uses the `sk-cp-` prefix
- Authenticates one principal
- Has exactly one validated scope
- Stores a non-empty explicit permission ceiling
- May expire
- May name a parent access key
- Stores only a token hash and display prefix
- Returns the full token once, when minted

There is no omitted permission list meaning everything. A key's effective authority is always the
intersection of its stored ceiling and the principal's current standing grants.

Browser sessions enter the same evaluator with instance credential scope and an all-permissions
ceiling. The human's current roles still determine the standing authority for each target.

### Issuance and delegation

The collection URL determines a new key's scope. Creating one requires `access-keys.issue` at that
scope, and the requested permissions must be contained by both the acting principal's and receiving
principal's current standing authority.

When an access key creates another access key, the child must also satisfy these attenuation rules:

- Its permission ceiling is a strict subset of the issuer's ceiling
- It cannot carry `access-keys.issue`
- It cannot outlive the issuer
- Its scope must be covered by the issuer's scope
- It records the issuer as its parent

Verification walks the parent chain. A missing, expired, or revoked ancestor invalidates every
descendant. Revoking a key uses the key id, then checks authority against that key's stored scope.

CLI login may present its current access key on the one-time delivery request. The server resolves
the token hash to the unique key id and retires exactly that key and its descendants only when its
principal and scope match the approved login. Labels are display metadata and never identify keys.

Self-service identity responses are scope-aware. Organization- and workspace-scoped keys cannot use
`/auth/me` or `/enroll` to enumerate their principal's other organizations. Founding a personal
organization requires a browser session.

## Data-plane authority

A managed data plane uses an ordinary access key for a service-account principal. The key must have
instance or organization scope and exactly these permissions:

```text
bundles.read
usage.ingest
data-planes.heartbeat
```

The principal must currently hold all three permissions at that scope. The role that supplies them
is otherwise irrelevant. This allows a service account with broader standing authority to use a
strict runtime key without turning the role name into a second authorization system.

Instance scope is the default and registers a global data-plane instance with `org_id = null`.
Organization scope is available for a dedicated data plane and records that organization on its
heartbeat. The same credential supports only the actions the data plane performs:

- Poll the latest bundle, optionally selecting an organization when instance-scoped
- Ingest usage events after every event's workspace scope is authorized
- Heartbeat at the credential scope

Control-plane startup seeds one configured pool token into the existing service-account and access-key
tables before a human claims the instance. The token may resolve from a shared local file or an
orchestrator-injected environment variable. Startup is idempotent, serializes
concurrent replicas with a database advisory lock, and never reactivates a revoked key.

## Adding authority

Adding a protected operation requires all of the following:

1. Add a `Permission` only when no existing permission describes the authority
2. Add it explicitly to the roles that should receive it
3. Declare the permission and scope resolver on the route
4. Keep conditional decisions in `authority`, never in a route
5. Test an allowed role, a lower role, a narrower scope, and a narrower credential ceiling
6. Regenerate OpenAPI and clients

Do not infer permissions from HTTP methods, route names, key labels, or JSON field overlap. The
permission catalog, role grants, scope hierarchy, and credential ceiling are the complete model.
