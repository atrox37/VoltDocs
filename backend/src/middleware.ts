import type { NextFunction, Request, Response } from "express";
import { config } from "./config.js";
import type { CurrentUser } from "./types/http.js";

function parseJwtPayload(token: string): Record<string, unknown> {
  const payload = token.split(".")[1];
  if (!payload) return {};
  const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
  return JSON.parse(Buffer.from(normalized, "base64").toString("utf8"));
}

export function authMiddleware(req: Request, res: Response, next: NextFunction) {
  const header = req.header("authorization") ?? "";
  const token = header.startsWith("Bearer ") ? header.slice("Bearer ".length) : "";

  if (config.requireAuth && !token) {
    res.status(401).json({ error: "Missing bearer token" });
    return;
  }

  let user: CurrentUser = {
    id: "dev-user",
    email: "dev@example.com",
    name: "Development User"
  };

  if (token) {
    try {
      const payload = parseJwtPayload(token);
      const sub = String(payload.sub ?? payload.username ?? "unknown");
      const email = String(payload.email ?? "");
      user = {
        id: sub,
        email,
        name: String(payload.name ?? email.split("@")[0] ?? sub)
      };
    } catch {
      if (config.requireAuth) {
        res.status(401).json({ error: "Invalid bearer token" });
        return;
      }
    }
  }

  (req as Request & { user: CurrentUser }).user = user;
  next();
}

export function asyncRoute<T extends Request>(
  handler: (req: T, res: Response, next: NextFunction) => Promise<unknown>
) {
  return (req: Request, res: Response, next: NextFunction) => {
    handler(req as T, res, next).catch(next);
  };
}

