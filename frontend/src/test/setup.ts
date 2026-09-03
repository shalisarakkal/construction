import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Explicit cleanup since the project doesn't run Vitest in `globals` mode --
// @testing-library/react's automatic afterEach-based cleanup only registers
// when it can find a global `afterEach`.
afterEach(() => {
  cleanup();
});
