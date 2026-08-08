import { Router, type IRouter } from "express";
import { desc, eq, sql } from "drizzle-orm";
import {
  db,
  organizationsTable,
  usersTable,
  workspacesTable,
  managementKeysTable,
  inferenceKeysTable,
  activityEventsTable,
} from "@workspace/db";
import {
  GetDashboardSummaryResponse,
  GetRecentActivityResponse,
} from "@workspace/api-zod";
import { isoReq } from "../lib/gateway";

const router: IRouter = Router();

router.get("/dashboard/summary", async (_req, res): Promise<void> => {
  const countExpr = { count: sql<number>`count(*)::int` };
  const [[orgs], [users], [workspaces], [mgmtKeys], [infKeys], [activeInfKeys]] =
    await Promise.all([
      db.select(countExpr).from(organizationsTable),
      db.select(countExpr).from(usersTable),
      db.select(countExpr).from(workspacesTable),
      db.select(countExpr).from(managementKeysTable),
      db.select(countExpr).from(inferenceKeysTable),
      db
        .select({ count: sql<number>`count(*)::int` })
        .from(inferenceKeysTable)
        .where(eq(inferenceKeysTable.status, "active")),
    ]);

  res.json(
    GetDashboardSummaryResponse.parse({
      organizationCount: orgs.count,
      userCount: users.count,
      workspaceCount: workspaces.count,
      managementKeyCount: mgmtKeys.count,
      inferenceKeyCount: infKeys.count,
      activeInferenceKeyCount: activeInfKeys.count,
    }),
  );
});

router.get("/dashboard/activity", async (_req, res): Promise<void> => {
  const events = await db
    .select()
    .from(activityEventsTable)
    .orderBy(desc(activityEventsTable.createdAt), desc(activityEventsTable.id))
    .limit(20);
  res.json(
    GetRecentActivityResponse.parse(
      events.map((e) => ({ ...e, createdAt: isoReq(e.createdAt) })),
    ),
  );
});

export default router;
