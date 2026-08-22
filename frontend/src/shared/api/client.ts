import createClient from "openapi-fetch";
import type { paths } from "./openapi";
import { getToken } from "../lib/auth";

// One typed client. No hand-written endpoint functions — `paths` (generated
// from the committed openapi.json snapshot) drives every call, so a backend
// contract change surfaces here as a type error, not a runtime failure.
export const api = createClient<paths>({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? "",
});

api.use({
  async onRequest({ request }) {
    const token = getToken();
    if (token) {
      request.headers.set("Authorization", `Bearer ${token}`);
    }
    return request;
  },
});
