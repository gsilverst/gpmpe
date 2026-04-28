import { describe, expect, it, vi } from "vitest";

import {
  createChatSession,
  fetchArtifacts,
  fetchDataManagerBusinesses,
  fetchDataManagerCampaignDetail,
  listBusinesses,
  postChatMessage,
  renderArtifact,
  saveCampaign,
  syncYamlData,
} from "../src/lib/api";

describe("data manager api client", () => {
  it("loads business list", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        items: [
          {
            display_name: "acme",
            legal_name: "Acme Promotions LLC",
            timezone: "America/New_York",
            is_active: true,
          },
        ],
      }),
    });

    vi.stubGlobal("fetch", mockFetch);

    const payload = await fetchDataManagerBusinesses("http://localhost:8000");

    expect(payload[0].display_name).toBe("acme");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/data-manager/businesses",
      expect.any(Object)
    );
  });

  it("loads campaign detail with qualifier", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        business: { display_name: "acme" },
        campaign: { campaign_name: "mothersday", qualifier: "2026" },
      }),
    });

    vi.stubGlobal("fetch", mockFetch);

    const payload = await fetchDataManagerCampaignDetail(
      "acme",
      "mothersday",
      "2026",
      "http://localhost:8000"
    );

    expect(payload.campaign.qualifier).toBe("2026");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/data-manager/businesses/acme/campaigns/mothersday?qualifier=2026",
      expect.any(Object)
    );
  });

  it("posts save campaign request", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        campaign_id: 42,
        saved: true,
        auto_commit: {
          enabled: true,
          performed: true,
          commit_id: "abc123",
        },
      }),
    });

    vi.stubGlobal("fetch", mockFetch);

    const payload = await saveCampaign(42, "Save from UI", "http://localhost:8000");

    expect(payload.saved).toBe(true);
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/campaigns/42/save",
      expect.objectContaining({
        method: "POST",
      })
    );
  });

  it("posts render artifact request", async () => {
    const artifact = {
      id: 1,
      campaign_id: 5,
      artifact_type: "flyer",
      file_path: "/out/summer-flyer.pdf",
      checksum: "abc123",
      status: "complete",
      created_at: "2026-01-01T00:00:00",
    };

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => artifact,
    });

    vi.stubGlobal("fetch", mockFetch);

    const result = await renderArtifact(5, "flyer", "http://localhost:8000");

    expect(result.id).toBe(1);
    expect(result.artifact_type).toBe("flyer");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/campaigns/5/render",
      expect.objectContaining({ method: "POST" })
    );
  });

  it("fetches artifact list", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        items: [
          {
            id: 1,
            campaign_id: 5,
            artifact_type: "flyer",
            file_path: "/out/summer-flyer.pdf",
            checksum: "abc123",
            status: "complete",
            created_at: "2026-01-01T00:00:00",
          },
        ],
      }),
    });

    vi.stubGlobal("fetch", mockFetch);

    const items = await fetchArtifacts(5, "http://localhost:8000");

    expect(items).toHaveLength(1);
    expect(items[0].artifact_type).toBe("flyer");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/campaigns/5/artifacts",
      expect.any(Object)
    );
  });

  it("loads core business list endpoint", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        {
          id: 11,
          legal_name: "Acme LLC",
          display_name: "Acme",
          timezone: "America/New_York",
          is_active: true,
        },
      ],
    });

    vi.stubGlobal("fetch", mockFetch);

    const businesses = await listBusinesses("http://localhost:8000");

    expect(businesses[0].id).toBe(11);
    expect(mockFetch).toHaveBeenCalledWith("http://localhost:8000/businesses", expect.any(Object));
  });

  it("creates chat session and sends message", async () => {
    const mockFetch = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ session_id: "abc" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          session_id: "abc",
          result: { target: "campaign" },
          history: [{ role: "user", content: "set title to Summer" }],
        }),
      });

    vi.stubGlobal("fetch", mockFetch);

    const session = await createChatSession("http://localhost:8000");
    expect(session.session_id).toBe("abc");

    const message = await postChatMessage("abc", 7, "set title to Summer", "http://localhost:8000");
    expect(message.history).toHaveLength(1);
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/chat/sessions/abc/messages",
      expect.objectContaining({ method: "POST" })
    );
  });

  it("runs manual yaml sync", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ businesses_synced: 1, campaigns_synced: 1, data_dir: "/tmp/data" }),
    });

    vi.stubGlobal("fetch", mockFetch);

    const result = await syncYamlData("http://localhost:8000");
    expect(result.businesses_synced).toBe(1);
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/data/sync",
      expect.objectContaining({ method: "POST" })
    );
  });
});
