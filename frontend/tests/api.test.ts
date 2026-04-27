import { describe, expect, it, vi } from "vitest";

import { fetchBackendHealth } from "../src/lib/api";

describe("fetchBackendHealth", () => {
  it("calls backend health endpoint and returns payload", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        status: "ok",
        database: "ok",
        output_dir: "/tmp/output",
      }),
    });

    vi.stubGlobal("fetch", mockFetch);

    const payload = await fetchBackendHealth("http://localhost:8000");

    expect(mockFetch).toHaveBeenCalledWith("http://localhost:8000/health", expect.any(Object));
    expect(payload.status).toBe("ok");
  });

  it("throws when the backend response is non-success", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
    });

    vi.stubGlobal("fetch", mockFetch);

    await expect(fetchBackendHealth("http://localhost:8000")).rejects.toThrow(
      "Backend health request failed: 503"
    );
  });
});
