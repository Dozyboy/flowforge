import { describe, expect, it } from "vitest";

import { ApiError, errorMessage } from "@/lib/api-client";
import { safeNextPath } from "@/lib/navigation";

describe("errorMessage", () => {
  it("prefers field errors from validation problems", () => {
    const error = new ApiError(422, "validation_error", "Request validation failed", [
      { field: "email", message: "value is not a valid email address" },
      { field: "full_name", message: "String should have at least 1 character" },
    ]);
    expect(errorMessage(error)).toBe(
      "email: value is not a valid email address. full name: String should have at least 1 character",
    );
  });

  it("falls back to the problem detail", () => {
    expect(errorMessage(new ApiError(409, "conflict", "Already exists"))).toBe("Already exists");
    expect(errorMessage("weird")).toBe("Something went wrong");
  });
});

describe("safeNextPath", () => {
  it("allows only same-site relative paths", () => {
    expect(safeNextPath("/app/123")).toBe("/app/123");
    expect(safeNextPath("//evil.com")).toBeNull();
    expect(safeNextPath("/\\evil.com")).toBeNull();
    expect(safeNextPath("https://evil.com")).toBeNull();
    expect(safeNextPath(null)).toBeNull();
  });
});
