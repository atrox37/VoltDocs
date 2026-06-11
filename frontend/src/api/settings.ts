import { get, put } from "./client";

export function getSettings() {
  return get<{ settings: Record<string, string> }>("/settings");
}

export function updateSettings(settings: Record<string, string>) {
  return put<{ ok: boolean }>("/settings", { settings });
}
