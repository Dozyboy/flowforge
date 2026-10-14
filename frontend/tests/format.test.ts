import { describe, expect, it } from "vitest";

import { duration } from "@/lib/format";

describe("duration", () => {
  it("keeps short runs readable", () => {
    expect(duration(0.0123)).toBe("12 ms");
    expect(duration(0)).toBe("1 ms");
    expect(duration(4.26)).toBe("4.3s");
    expect(duration(42)).toBe("42s");
    expect(duration(150)).toBe("3m");
    expect(duration(null)).toBe("—");
  });
});
