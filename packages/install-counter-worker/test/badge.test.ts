import { describe, expect, it } from "vitest";
import { badgeJson, installsJson } from "../src/badge";

describe("formatters", () => {
  it("installsJson returns the raw count", () => {
    expect(installsJson(12345)).toEqual({ installs: 12345 });
    expect(installsJson(null)).toEqual({ installs: null });
  });

  it("badgeJson is shields-endpoint shaped with thousands separators", () => {
    expect(badgeJson(12345)).toEqual({
      schemaVersion: 1,
      label: "installs",
      message: "12,345",
      color: "blue",
    });
  });

  it("badgeJson degrades to a valid non-empty message when count unknown", () => {
    const b = badgeJson(null);
    expect(b.schemaVersion).toBe(1);
    expect(b.message).toBe("unknown");
    expect(b.color).toBe("lightgrey");
  });
});
