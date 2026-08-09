import { Router, type IRouter } from "express";
import { eq, and, sql } from "drizzle-orm";
import {
  db,
  organizationsTable,
  orgMembersTable,
  workspacesTable,
  usersTable,
  managementKeysTable,
} from "@workspace/db";
import {
  ListOrganizationsResponse,
  CreateOrganizationBody,
  CreateOrganizationResponse,
  GetOrganizationParams,
  GetOrganizationResponse,
  UpdateOrganizationParams,
  UpdateOrganizationBody,
  ListOrgMembersParams,
  ListOrgMembersResponse,
  AddOrgMemberParams,
  AddOrgMemberBody,
  AddOrgMemberResponse,
  UpdateOrgMemberParams,
  UpdateOrgMemberBody,
  RemoveOrgMemberParams,
  ListManagementKeysParams,
  ListManagementKeysResponse,
  CreateManagementKeyParams,
  CreateManagementKeyBody,
  CreateManagementKeyResponse,
  UpdateManagementKeyParams,
  UpdateManagementKeyBody,
  RevokeManagementKeyParams,
  ListWorkspacesParams,
  ListWorkspacesResponse,
  CreateWorkspaceParams,
  CreateWorkspaceBody,
  CreateWorkspaceResponse,
} from "@workspace/api-zod";
import { iso, isoReq, generateKey, logActivity } from "../lib/gateway";

const router: IRouter = Router();

async function orgWithCounts(orgId: number) {
  const [org] = await db
    .select()
    .from(organizationsTable)
    .where(eq(organizationsTable.id, orgId));
  if (!org) return null;
  const [{ count: memberCount }] = await db
    .select({ count: sql<number>`count(*)::int` })
    .from(orgMembersTable)
    .where(eq(orgMembersTable.orgId, orgId));
  const [{ count: workspaceCount }] = await db
    .select({ count: sql<number>`count(*)::int` })
    .from(workspacesTable)
    .where(eq(workspacesTable.orgId, orgId));
  return {
    id: org.id,
    name: org.name,
    slug: org.slug,
    description: org.description,
    createdAt: isoReq(org.createdAt),
    memberCount,
    workspaceCount,
  };
}

router.get("/organizations", async (_req, res): Promise<void> => {
  const orgs = await db
    .select({
      id: organizationsTable.id,
      name: organizationsTable.name,
      slug: organizationsTable.slug,
      description: organizationsTable.description,
      createdAt: organizationsTable.createdAt,
      memberCount: sql<number>`(select count(*)::int from org_members where org_members.org_id = organizations.id)`,
      workspaceCount: sql<number>`(select count(*)::int from workspaces where workspaces.org_id = organizations.id)`,
    })
    .from(organizationsTable)
    .orderBy(organizationsTable.createdAt);
  res.json(
    ListOrganizationsResponse.parse(
      orgs.map((o) => ({ ...o, createdAt: isoReq(o.createdAt) })),
    ),
  );
});

router.post("/organizations", async (req, res): Promise<void> => {
  const parsed = CreateOrganizationBody.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.message });
    return;
  }
  const [org] = await db
    .insert(organizationsTable)
    .values(parsed.data)
    .returning();
  await logActivity("org.created", `Organization "${org.name}" was created`);
  const full = await orgWithCounts(org.id);
  res.status(201).json(CreateOrganizationResponse.parse(full));
});

router.get("/organizations/:orgId", async (req, res): Promise<void> => {
  const params = GetOrganizationParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: params.error.message });
    return;
  }
  const org = await orgWithCounts(params.data.orgId);
  if (!org) {
    res.status(404).json({ error: "Organization not found" });
    return;
  }
  res.json(GetOrganizationResponse.parse(org));
});

router.patch("/organizations/:orgId", async (req, res): Promise<void> => {
  const params = UpdateOrganizationParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: params.error.message });
    return;
  }
  const body = UpdateOrganizationBody.safeParse(req.body);
  if (!body.success) {
    res.status(400).json({ error: body.error.message });
    return;
  }
  const [org] = await db
    .update(organizationsTable)
    .set(body.data)
    .where(eq(organizationsTable.id, params.data.orgId))
    .returning();
  if (!org) {
    res.status(404).json({ error: "Organization not found" });
    return;
  }
  const full = await orgWithCounts(org.id);
  res.json(GetOrganizationResponse.parse(full));
});

router.delete("/organizations/:orgId", async (req, res): Promise<void> => {
  const params = GetOrganizationParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: params.error.message });
    return;
  }
  const [org] = await db
    .delete(organizationsTable)
    .where(eq(organizationsTable.id, params.data.orgId))
    .returning();
  if (!org) {
    res.status(404).json({ error: "Organization not found" });
    return;
  }
  await logActivity("org.deleted", `Organization "${org.name}" was deleted`);
  res.sendStatus(204);
});

// --- Members ---

router.get("/organizations/:orgId/members", async (req, res): Promise<void> => {
  const params = ListOrgMembersParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: params.error.message });
    return;
  }
  const rows = await db
    .select({
      userId: orgMembersTable.userId,
      orgId: orgMembersTable.orgId,
      name: usersTable.name,
      email: usersTable.email,
      role: orgMembersTable.role,
      joinedAt: orgMembersTable.joinedAt,
    })
    .from(orgMembersTable)
    .innerJoin(usersTable, eq(orgMembersTable.userId, usersTable.id))
    .where(eq(orgMembersTable.orgId, params.data.orgId))
    .orderBy(orgMembersTable.joinedAt);
  res.json(
    ListOrgMembersResponse.parse(
      rows.map((r) => ({ ...r, joinedAt: isoReq(r.joinedAt) })),
    ),
  );
});

router.post("/organizations/:orgId/members", async (req, res): Promise<void> => {
  const params = AddOrgMemberParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: params.error.message });
    return;
  }
  const body = AddOrgMemberBody.safeParse(req.body);
  if (!body.success) {
    res.status(400).json({ error: body.error.message });
    return;
  }
  const [user] = await db
    .select()
    .from(usersTable)
    .where(eq(usersTable.id, body.data.userId));
  if (!user) {
    res.status(400).json({ error: "User not found" });
    return;
  }
  const [existing] = await db
    .select()
    .from(orgMembersTable)
    .where(
      and(
        eq(orgMembersTable.orgId, params.data.orgId),
        eq(orgMembersTable.userId, body.data.userId),
      ),
    );
  if (existing) {
    res.status(400).json({ error: "User is already a member of this organization" });
    return;
  }
  const [member] = await db
    .insert(orgMembersTable)
    .values({
      orgId: params.data.orgId,
      userId: body.data.userId,
      role: body.data.role,
    })
    .returning();
  await logActivity("user.added", `${user.name} joined an organization as ${body.data.role}`);
  res.status(201).json(
    AddOrgMemberResponse.parse({
      userId: member.userId,
      orgId: member.orgId,
      name: user.name,
      email: user.email,
      role: member.role,
      joinedAt: isoReq(member.joinedAt),
    }),
  );
});

router.patch(
  "/organizations/:orgId/members/:userId",
  async (req, res): Promise<void> => {
    const params = UpdateOrgMemberParams.safeParse(req.params);
    if (!params.success) {
      res.status(400).json({ error: params.error.message });
      return;
    }
    const body = UpdateOrgMemberBody.safeParse(req.body);
    if (!body.success) {
      res.status(400).json({ error: body.error.message });
      return;
    }
    const [member] = await db
      .update(orgMembersTable)
      .set({ role: body.data.role })
      .where(
        and(
          eq(orgMembersTable.orgId, params.data.orgId),
          eq(orgMembersTable.userId, params.data.userId),
        ),
      )
      .returning();
    if (!member) {
      res.status(404).json({ error: "Membership not found" });
      return;
    }
    const [user] = await db
      .select()
      .from(usersTable)
      .where(eq(usersTable.id, member.userId));
    res.json(
      AddOrgMemberResponse.parse({
        userId: member.userId,
        orgId: member.orgId,
        name: user?.name ?? "",
        email: user?.email ?? "",
        role: member.role,
        joinedAt: isoReq(member.joinedAt),
      }),
    );
  },
);

router.delete(
  "/organizations/:orgId/members/:userId",
  async (req, res): Promise<void> => {
    const params = RemoveOrgMemberParams.safeParse(req.params);
    if (!params.success) {
      res.status(400).json({ error: params.error.message });
      return;
    }
    const [member] = await db
      .delete(orgMembersTable)
      .where(
        and(
          eq(orgMembersTable.orgId, params.data.orgId),
          eq(orgMembersTable.userId, params.data.userId),
        ),
      )
      .returning();
    if (!member) {
      res.status(404).json({ error: "Membership not found" });
      return;
    }
    res.sendStatus(204);
  },
);

// --- Management keys ---

router.get(
  "/organizations/:orgId/management-keys",
  async (req, res): Promise<void> => {
    const params = ListManagementKeysParams.safeParse(req.params);
    if (!params.success) {
      res.status(400).json({ error: params.error.message });
      return;
    }
    const keys = await db
      .select()
      .from(managementKeysTable)
      .where(eq(managementKeysTable.orgId, params.data.orgId))
      .orderBy(managementKeysTable.createdAt);
    res.json(
      ListManagementKeysResponse.parse(
        keys.map((k) => ({
          ...k,
          createdAt: isoReq(k.createdAt),
          lastUsedAt: iso(k.lastUsedAt),
        })),
      ),
    );
  },
);

router.post(
  "/organizations/:orgId/management-keys",
  async (req, res): Promise<void> => {
    const params = CreateManagementKeyParams.safeParse(req.params);
    if (!params.success) {
      res.status(400).json({ error: params.error.message });
      return;
    }
    const body = CreateManagementKeyBody.safeParse(req.body);
    if (!body.success) {
      res.status(400).json({ error: body.error.message });
      return;
    }
    const { secret, prefix } = generateKey("mk");
    const [key] = await db
      .insert(managementKeysTable)
      .values({ orgId: params.data.orgId, name: body.data.name, prefix })
      .returning();
    await logActivity("key.created", `Management key "${key.name}" was created`);
    res.status(201).json(
      CreateManagementKeyResponse.parse({
        id: key.id,
        name: key.name,
        prefix: key.prefix,
        status: key.status,
        createdAt: isoReq(key.createdAt),
        secret,
      }),
    );
  },
);

router.patch(
  "/organizations/:orgId/management-keys/:keyId",
  async (req, res): Promise<void> => {
    const params = UpdateManagementKeyParams.safeParse(req.params);
    if (!params.success) {
      res.status(400).json({ error: params.error.message });
      return;
    }
    const body = UpdateManagementKeyBody.safeParse(req.body);
    if (!body.success) {
      res.status(400).json({ error: body.error.message });
      return;
    }
    const [key] = await db
      .update(managementKeysTable)
      .set(body.data)
      .where(
        and(
          eq(managementKeysTable.id, params.data.keyId),
          eq(managementKeysTable.orgId, params.data.orgId),
        ),
      )
      .returning();
    if (!key) {
      res.status(404).json({ error: "Key not found" });
      return;
    }
    res.json({
      ...key,
      createdAt: isoReq(key.createdAt),
      lastUsedAt: iso(key.lastUsedAt),
    });
  },
);

router.delete(
  "/organizations/:orgId/management-keys/:keyId",
  async (req, res): Promise<void> => {
    const params = RevokeManagementKeyParams.safeParse(req.params);
    if (!params.success) {
      res.status(400).json({ error: params.error.message });
      return;
    }
    const [key] = await db
      .delete(managementKeysTable)
      .where(
        and(
          eq(managementKeysTable.id, params.data.keyId),
          eq(managementKeysTable.orgId, params.data.orgId),
        ),
      )
      .returning();
    if (!key) {
      res.status(404).json({ error: "Key not found" });
      return;
    }
    await logActivity("key.revoked", `Management key "${key.name}" was revoked`);
    res.sendStatus(204);
  },
);

// --- Workspaces under org ---

router.get(
  "/organizations/:orgId/workspaces",
  async (req, res): Promise<void> => {
    const params = ListWorkspacesParams.safeParse(req.params);
    if (!params.success) {
      res.status(400).json({ error: params.error.message });
      return;
    }
    const rows = await db
      .select({
        id: workspacesTable.id,
        orgId: workspacesTable.orgId,
        orgName: organizationsTable.name,
        name: workspacesTable.name,
        slug: workspacesTable.slug,
        description: workspacesTable.description,
        createdAt: workspacesTable.createdAt,
        memberCount: sql<number>`(select count(*)::int from workspace_members where workspace_members.workspace_id = workspaces.id)`,
        inferenceKeyCount: sql<number>`(select count(*)::int from inference_keys where inference_keys.workspace_id = workspaces.id)`,
      })
      .from(workspacesTable)
      .innerJoin(
        organizationsTable,
        eq(workspacesTable.orgId, organizationsTable.id),
      )
      .where(eq(workspacesTable.orgId, params.data.orgId))
      .orderBy(workspacesTable.createdAt);
    res.json(
      ListWorkspacesResponse.parse(
        rows.map((w) => ({ ...w, createdAt: isoReq(w.createdAt) })),
      ),
    );
  },
);

router.post(
  "/organizations/:orgId/workspaces",
  async (req, res): Promise<void> => {
    const params = CreateWorkspaceParams.safeParse(req.params);
    if (!params.success) {
      res.status(400).json({ error: params.error.message });
      return;
    }
    const body = CreateWorkspaceBody.safeParse(req.body);
    if (!body.success) {
      res.status(400).json({ error: body.error.message });
      return;
    }
    const [org] = await db
      .select()
      .from(organizationsTable)
      .where(eq(organizationsTable.id, params.data.orgId));
    if (!org) {
      res.status(404).json({ error: "Organization not found" });
      return;
    }
    const [ws] = await db
      .insert(workspacesTable)
      .values({ ...body.data, orgId: params.data.orgId })
      .returning();
    await logActivity(
      "workspace.created",
      `Workspace "${ws.name}" was created in ${org.name}`,
    );
    res.status(201).json(
      CreateWorkspaceResponse.parse({
        ...ws,
        orgName: org.name,
        createdAt: isoReq(ws.createdAt),
        memberCount: 0,
        inferenceKeyCount: 0,
      }),
    );
  },
);

export default router;
