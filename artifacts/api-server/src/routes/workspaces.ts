import { Router, type IRouter } from "express";
import { eq, and, sql } from "drizzle-orm";
import {
  db,
  organizationsTable,
  workspacesTable,
  workspaceMembersTable,
  usersTable,
  inferenceKeysTable,
} from "@workspace/db";
import {
  GetWorkspaceParams,
  GetWorkspaceResponse,
  UpdateWorkspaceParams,
  UpdateWorkspaceBody,
  DeleteWorkspaceParams,
  ListWorkspaceMembersParams,
  ListWorkspaceMembersResponse,
  AddWorkspaceMemberParams,
  AddWorkspaceMemberBody,
  AddWorkspaceMemberResponse,
  RemoveWorkspaceMemberParams,
  ListInferenceKeysParams,
  ListInferenceKeysResponse,
  CreateInferenceKeyParams,
  CreateInferenceKeyBody,
  CreateInferenceKeyResponse,
  UpdateInferenceKeyParams,
  UpdateInferenceKeyBody,
  RevokeInferenceKeyParams,
} from "@workspace/api-zod";
import { iso, isoReq, generateKey, logActivity } from "../lib/gateway";

const router: IRouter = Router();

async function workspaceWithCounts(workspaceId: number) {
  const [row] = await db
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
    .where(eq(workspacesTable.id, workspaceId));
  if (!row) return null;
  return { ...row, createdAt: isoReq(row.createdAt) };
}

router.get("/workspaces/:workspaceId", async (req, res): Promise<void> => {
  const params = GetWorkspaceParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: params.error.message });
    return;
  }
  const ws = await workspaceWithCounts(params.data.workspaceId);
  if (!ws) {
    res.status(404).json({ error: "Workspace not found" });
    return;
  }
  res.json(GetWorkspaceResponse.parse(ws));
});

router.patch("/workspaces/:workspaceId", async (req, res): Promise<void> => {
  const params = UpdateWorkspaceParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: params.error.message });
    return;
  }
  const body = UpdateWorkspaceBody.safeParse(req.body);
  if (!body.success) {
    res.status(400).json({ error: body.error.message });
    return;
  }
  const [ws] = await db
    .update(workspacesTable)
    .set(body.data)
    .where(eq(workspacesTable.id, params.data.workspaceId))
    .returning();
  if (!ws) {
    res.status(404).json({ error: "Workspace not found" });
    return;
  }
  const full = await workspaceWithCounts(ws.id);
  res.json(GetWorkspaceResponse.parse(full));
});

router.delete("/workspaces/:workspaceId", async (req, res): Promise<void> => {
  const params = DeleteWorkspaceParams.safeParse(req.params);
  if (!params.success) {
    res.status(400).json({ error: params.error.message });
    return;
  }
  const [ws] = await db
    .delete(workspacesTable)
    .where(eq(workspacesTable.id, params.data.workspaceId))
    .returning();
  if (!ws) {
    res.status(404).json({ error: "Workspace not found" });
    return;
  }
  await logActivity("workspace.deleted", `Workspace "${ws.name}" was deleted`);
  res.sendStatus(204);
});

// --- Members ---

router.get(
  "/workspaces/:workspaceId/members",
  async (req, res): Promise<void> => {
    const params = ListWorkspaceMembersParams.safeParse(req.params);
    if (!params.success) {
      res.status(400).json({ error: params.error.message });
      return;
    }
    const rows = await db
      .select({
        userId: workspaceMembersTable.userId,
        workspaceId: workspaceMembersTable.workspaceId,
        name: usersTable.name,
        email: usersTable.email,
        addedAt: workspaceMembersTable.addedAt,
      })
      .from(workspaceMembersTable)
      .innerJoin(usersTable, eq(workspaceMembersTable.userId, usersTable.id))
      .where(eq(workspaceMembersTable.workspaceId, params.data.workspaceId))
      .orderBy(workspaceMembersTable.addedAt);
    res.json(
      ListWorkspaceMembersResponse.parse(
        rows.map((r) => ({ ...r, addedAt: isoReq(r.addedAt) })),
      ),
    );
  },
);

router.post(
  "/workspaces/:workspaceId/members",
  async (req, res): Promise<void> => {
    const params = AddWorkspaceMemberParams.safeParse(req.params);
    if (!params.success) {
      res.status(400).json({ error: params.error.message });
      return;
    }
    const body = AddWorkspaceMemberBody.safeParse(req.body);
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
      .from(workspaceMembersTable)
      .where(
        and(
          eq(workspaceMembersTable.workspaceId, params.data.workspaceId),
          eq(workspaceMembersTable.userId, body.data.userId),
        ),
      );
    if (existing) {
      res.status(400).json({ error: "User is already a member of this workspace" });
      return;
    }
    const [member] = await db
      .insert(workspaceMembersTable)
      .values({
        workspaceId: params.data.workspaceId,
        userId: body.data.userId,
      })
      .returning();
    await logActivity("user.added", `${user.name} was added to a workspace`);
    res.status(201).json(
      AddWorkspaceMemberResponse.parse({
        userId: member.userId,
        workspaceId: member.workspaceId,
        name: user.name,
        email: user.email,
        addedAt: isoReq(member.addedAt),
      }),
    );
  },
);

router.delete(
  "/workspaces/:workspaceId/members/:userId",
  async (req, res): Promise<void> => {
    const params = RemoveWorkspaceMemberParams.safeParse(req.params);
    if (!params.success) {
      res.status(400).json({ error: params.error.message });
      return;
    }
    const [member] = await db
      .delete(workspaceMembersTable)
      .where(
        and(
          eq(workspaceMembersTable.workspaceId, params.data.workspaceId),
          eq(workspaceMembersTable.userId, params.data.userId),
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

// --- Inference keys ---

router.get(
  "/workspaces/:workspaceId/inference-keys",
  async (req, res): Promise<void> => {
    const params = ListInferenceKeysParams.safeParse(req.params);
    if (!params.success) {
      res.status(400).json({ error: params.error.message });
      return;
    }
    const keys = await db
      .select()
      .from(inferenceKeysTable)
      .where(eq(inferenceKeysTable.workspaceId, params.data.workspaceId))
      .orderBy(inferenceKeysTable.createdAt);
    res.json(
      ListInferenceKeysResponse.parse(
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
  "/workspaces/:workspaceId/inference-keys",
  async (req, res): Promise<void> => {
    const params = CreateInferenceKeyParams.safeParse(req.params);
    if (!params.success) {
      res.status(400).json({ error: params.error.message });
      return;
    }
    const body = CreateInferenceKeyBody.safeParse(req.body);
    if (!body.success) {
      res.status(400).json({ error: body.error.message });
      return;
    }
    const { secret, prefix } = generateKey("ik");
    const [key] = await db
      .insert(inferenceKeysTable)
      .values({
        workspaceId: params.data.workspaceId,
        name: body.data.name,
        prefix,
      })
      .returning();
    await logActivity("key.created", `Inference key "${key.name}" was created`);
    res.status(201).json(
      CreateInferenceKeyResponse.parse({
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
  "/workspaces/:workspaceId/inference-keys/:keyId",
  async (req, res): Promise<void> => {
    const params = UpdateInferenceKeyParams.safeParse(req.params);
    if (!params.success) {
      res.status(400).json({ error: params.error.message });
      return;
    }
    const body = UpdateInferenceKeyBody.safeParse(req.body);
    if (!body.success) {
      res.status(400).json({ error: body.error.message });
      return;
    }
    const [key] = await db
      .update(inferenceKeysTable)
      .set(body.data)
      .where(
        and(
          eq(inferenceKeysTable.id, params.data.keyId),
          eq(inferenceKeysTable.workspaceId, params.data.workspaceId),
        ),
      )
      .returning();
    if (!key) {
      res.status(404).json({ error: "Key not found" });
      return;
    }
    if (body.data.status === "revoked") {
      await logActivity("key.revoked", `Inference key "${key.name}" was revoked`);
    }
    res.json({
      ...key,
      createdAt: isoReq(key.createdAt),
      lastUsedAt: iso(key.lastUsedAt),
    });
  },
);

router.delete(
  "/workspaces/:workspaceId/inference-keys/:keyId",
  async (req, res): Promise<void> => {
    const params = RevokeInferenceKeyParams.safeParse(req.params);
    if (!params.success) {
      res.status(400).json({ error: params.error.message });
      return;
    }
    const [key] = await db
      .delete(inferenceKeysTable)
      .where(
        and(
          eq(inferenceKeysTable.id, params.data.keyId),
          eq(inferenceKeysTable.workspaceId, params.data.workspaceId),
        ),
      )
      .returning();
    if (!key) {
      res.status(404).json({ error: "Key not found" });
      return;
    }
    await logActivity("key.revoked", `Inference key "${key.name}" was revoked`);
    res.sendStatus(204);
  },
);

export default router;
