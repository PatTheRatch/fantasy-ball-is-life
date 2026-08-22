import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Unmount and clear the DOM after each test. Without this, later tests can
// match stale elements from earlier renders (e.g. two `role="alert"` nodes).
afterEach(() => cleanup());
