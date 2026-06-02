import type { Request } from "express";

export interface CurrentUser {
  id: string;
  email: string;
  name: string;
}

export interface AuthedRequest extends Request {
  user: CurrentUser;
}

