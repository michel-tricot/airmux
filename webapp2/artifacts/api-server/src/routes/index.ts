import { Router, type IRouter } from "express";
import healthRouter from "./health";
import dashboardRouter from "./dashboard";
import organizationsRouter from "./organizations";
import workspacesRouter from "./workspaces";
import usersRouter from "./users";

const router: IRouter = Router();

router.use(healthRouter);
router.use(dashboardRouter);
router.use(organizationsRouter);
router.use(workspacesRouter);
router.use(usersRouter);

export default router;
