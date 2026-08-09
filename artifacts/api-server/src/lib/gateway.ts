import { randomBytes } from "node:crypto";
import { db, activityEventsTable } from "@workspace/db";

export function iso(d: Date | null): string | null {
  return d ? d.toISOString() : null;
}

export function isoReq(d: Date): string {
  return d.toISOString();
}

export function generateKey(kind: "mk" | "ik"): {
  secret: string;
  prefix: string;
} {
  const body = randomBytes(24).toString("base64url");
  const secret = `${kind}_live_${body}`;
  const prefix = secret.slice(0, 12);
  return { secret, prefix };
}

export async function logActivity(type: string, message: string): Promise<void> {
  await db.insert(activityEventsTable).values({ type, message });
}

export function parseIntParam(value: string | string[] | undefined): number {
  const raw = Array.isArray(value) ? value[0] : value;
  return parseInt(raw ?? "", 10);
}
