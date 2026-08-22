const STORAGE_KEY = "fcp.devToken";

// Dev-only token shim. Reads a real Supabase-issued JWT so the app can attach a
// bearer token without the full Supabase auth flow (a later bite). This never
// bypasses auth — the backend still verifies the token end-to-end.
export function getToken(): string | undefined {
  const fromEnv = import.meta.env.VITE_DEV_TOKEN;
  if (fromEnv) return fromEnv;
  try {
    return localStorage.getItem(STORAGE_KEY) ?? undefined;
  } catch {
    return undefined;
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, token);
  } catch {
    // Non-browser or storage disabled — the env var is the fallback.
  }
}
