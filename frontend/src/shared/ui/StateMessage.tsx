export type StateMessageKind = "loading" | "error" | "empty" | "not-synced";

// The empty/stale-state vocabulary the rest of the app inherits:
//   loading    — request in flight
//   error      — the request failed (401/403/network)
//   empty      — valid response, nothing to show (`data: []`), not an error
//   not-synced — valid response but `as_of: null` (never synced yet)
// `stale: true` is rendered separately (a banner over real numbers), not here.
const DEFAULT_COPY: Record<StateMessageKind, string> = {
  loading: "Loading…",
  error: "Something went wrong.",
  empty: "No results yet.",
  "not-synced": "Not yet synced.",
};

export function StateMessage({
  kind,
  message,
}: {
  kind: StateMessageKind;
  message?: string;
}) {
  const copy = message ?? DEFAULT_COPY[kind];
  if (kind === "loading") {
    return <div role="status">{copy}</div>;
  }
  if (kind === "error") {
    return <div role="alert">{copy}</div>;
  }
  return <div>{copy}</div>;
}
