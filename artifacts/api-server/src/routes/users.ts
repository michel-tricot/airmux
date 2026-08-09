import { Router, type IRouter } from "express";
import { eq, sql } from "drizzle-orm";
import {
  db,
  usersTable,
  orgMembersTable,
  organizationsTable,
  workspacesTable,
  workspaceMembersTable,
} from "@workspace/db";
import {
  ListUsersResponse,
  CreateUserBody,
  CreateUserResponse,
  GetUserParams,
  GetUserResponse,
  UpdateUserParams,
  UpdateUserBody,
  DeleteUserParams,
  ListUserOrganizationsParams,
  ListUserOrganizationsResponse,
  ListUserWorkspacesParams,
  ListUserWorkspacesResponse,
} from "@workspace/api-zod";
import { isoReq, logActivity } from "../lib/gateway";

const router: IRouter = Router();

async function userWithCounts(userId: number) {
  const [user] = await db
    .select({
      id: usersTable.id,
      name: usersTable.name,
      email: usersTable.email,
      createdAt: usersTable.createdAt,
      orgCount: sql<number>`(select count(*)::int from org_members where org_members.user_id = users.id)`,
    })
    .from(usersTable)
    .where(eq(usersTable.id, userId));
  if (!user) return null;
  return { ...user, createdAt: isoReq(user.createdAt) };
}

router.get("/users", async (_req, res): Promise<void> => {
  const users = await db
    .select({
      id: usersTable.id,
      name: usersTable.name,
      email: usersTable.email,
      createdAt: usersTable.createdAt,
      orgCount: sql<number>`(select count(*)::int from org_members where org_members.user_id = users.id)`,
    })
    .from(usersTable)
    .orderBy(usersTable.createdAt);
  res.json(
    ListUsersResponse.parse(
      users.map((u) => ({ ...u, createdAt: isoReq(u.createdAt) })),
    ),
  );
});

router.post("/users", async (req, res): Promise<void> => {
  const parsed = CreateUserBody.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.message });
    return;
  }
  const [existing] = await db
    .select()
    .from(usersTable)
    .where(eq(usersTable.email, parsed.data.email));
  if (existing) {
    res.status(400).json({ error: "A user with this email already exists" });
    return;
  }
  const [user] = await db.insert(usersTable).values(parsed.data).returning();
  await logActivity("user.created", `User ${user.name} was created`);
  res.status(201).json(
    CreateUserResponse.parse({
      ...user,
      createdAt: isoReq(user.createdAt),
      orgCount: 0,
    }),
  );
});

router.get("/users/:userId", async (req, res): Promise<void> => {
  const params = GetUserParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: params.error.message });
    return;
  }
  const user = await userWithCounts(params.data.userId);
  if (!user) {
    res.status(404).json({ error: "User not found" });
    return;
  }
  res.json(GetUserResponse.parse(user));
});

router.patch("/users/:userId", async (req, res): Promise<void> => {
  const params = UpdateUserParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: params.error.message });
    return;
  }
  const body = UpdateUserBody.safeParse(req.body);
  if (!body.success) {
    res.status(400).json({ error: body.error.message });
    return;
  }
  const [user] = await db
    .update(usersTable)
    .set(body.data)
    .where(eq(usersTable.id, params.data.userId))
    .returning();
  if (!user) {
    res.status(404).json({ error: "User not found" });
    return;
  }
  const full = await userWithCounts(user.id);
  res.json(GetUserResponse.parse(full));
});

router.delete("/users/:userId", async (req, res): Promise<void> => {
  const params = DeleteUserParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: params.error.message });
    return;
  }
  const [user] = await db
    .delete(usersTable)
    .where(eq(usersTable.id, params.data.userId))
    .returning();
  if (!user) {
    res.status(404).json({ error: "User not found" });
    return;
  }
  await logActivity("user.deleted", `User ${user.name} was deleted`);
  res.sendStatus(204);
});

router.get(
  "/users/:userId/organizations",
  async (req, res): Promise<void> => {
    const params = ListUserOrganizationsParams.safeParse(req.params);
    if (!params.success) {
      res.status(400).json({ error: params.error.message });
      return;
    }
    const rows = await db
      .select({
        orgId: orgMembersTable.orgId,
        orgName: organizationsTable.name,
        orgSlug: organizationsTable.slug,
        role: orgMembersTable.role,
        joinedAt: orgMembersTable.joinedAt,
      })
      .from(orgMembersTable)
      .innerJoin(
        organizationsTable,
        eq(orgMembersTable.orgId, organizationsTable.id),
      )
      .where(eq(orgMembersTable.userId, params.data.userId))
      .orderBy(orgMembersTable.joinedAt);
    res.json(
      ListUserOrganizationsResponse.parse(
        rows.map((r) => ({ ...r, joinedAt: isoReq(r.joinedAt) })),
      ),
    );
  },
);

router.get(
  "/users/:userId/workspaces",
  async (req, res): Promise<void> => {
    const params = ListUserWorkspacesParams.safeParse(req.params);
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
      .from(workspaceMembersTable)
      .innerJoin(
        workspacesTable,
        eq(workspaceMembersTable.workspaceId, workspacesTable.id),
      )
      .innerJoin(
        organizationsTable,
        eq(workspacesTable.orgId, organizationsTable.id),
      )
      .where(eq(workspaceMembersTable.userId, params.data.userId))
      .orderBy(workspacesTable.createdAt);
    res.json(
      ListUserWorkspacesResponse.parse(
        rows.map((w) => ({ ...w, createdAt: isoReq(w.createdAt) })),
      ),
    );
  },
);

export default router;
