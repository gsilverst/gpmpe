import { describe, expect, it, vi } from "vitest";

import { fetchDataManagerBusinesses, fetchDataManagerCampaignDetail } from "../src/lib/api";

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
});
