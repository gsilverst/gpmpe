export type HealthResponse = {
  status: string;
  database: string;
  output_dir: string;
};

export type BusinessListItem = {
  display_name: string;
  legal_name: string;
  timezone: string;
  is_active: boolean;
};

export type BusinessDetail = BusinessListItem & {
  contacts: Array<{
    contact_type: string;
    contact_value: string;
    is_primary: boolean;
  }>;
  locations: Array<{
    label: string | null;
    line1: string;
    line2: string | null;
    city: string;
    state: string;
    postal_code: string;
    country: string;
    hours: Record<string, string>;
  }>;
  brand_theme: {
    name: string;
    primary_color: string | null;
    secondary_color: string | null;
    accent_color: string | null;
    font_family: string | null;
    logo_path: string | null;
  } | null;
};

export type CampaignListItem = {
  display_name: string;
  campaign_name: string;
  qualifier: string | null;
  title: string;
  objective: string | null;
  status: string;
  start_date: string | null;
  end_date: string | null;
};

export type CampaignDetail = CampaignListItem & {
  id: number;
  offers: Array<{
    offer_name: string;
    offer_type: string;
    offer_value: string | null;
    start_date: string | null;
    end_date: string | null;
    terms_text: string | null;
  }>;
  assets: Array<{
    asset_type: string;
    source_type: string;
    mime_type: string;
    source_path: string;
    width: number | null;
    height: number | null;
    metadata: Record<string, string>;
  }>;
  template_binding: {
    template_name: string;
    template_kind: string;
    size_spec: string | null;
    layout: Record<string, string>;
    default_values: Record<string, string>;
    override_values: Record<string, string>;
  } | null;
};

export type CampaignDetailResponse = {
  business: BusinessDetail;
  campaign: CampaignDetail;
};

export type CampaignSaveResponse = {
  campaign_id: number;
  saved: boolean;
  reason?: string;
  files?: string[];
  auto_commit: {
    enabled: boolean;
    performed: boolean;
    commit_id: string | null;
  };
};

export type BusinessRecord = {
  id: number;
  legal_name: string;
  display_name: string;
  timezone: string;
  is_active: boolean;
};

export type CampaignRecord = {
  id: number;
  business_id: number;
  campaign_name: string;
  campaign_key: string | null;
  title: string;
  objective: string | null;
  status: string;
  start_date: string | null;
  end_date: string | null;
};

export type CampaignLookupResponse = {
  campaign_name: string;
  matches: CampaignRecord[];
  prompt: string;
};

export type ChatSessionResponse = {
  session_id: string;
};

export type ChatHistoryItem = {
  role: string;
  content: string;
};

export type ChatMessageResponse = {
  session_id: string;
  result: Record<string, unknown>;
  history: ChatHistoryItem[];
};

export type DataSyncResponse = {
  businesses_synced: number;
  campaigns_synced: number;
  data_dir: string;
};

export function apiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}

async function fetchJson<T>(path: string, baseUrl = apiBaseUrl()): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    method: "GET",
    headers: {
      Accept: "application/json",
    },
    cache: "no-store",
  });

  if (!response.ok) {
    let detail = "";
    try {
      const errorPayload = (await response.json()) as { detail?: unknown };
      if (typeof errorPayload.detail === "string") {
        detail = ` - ${errorPayload.detail}`;
      }
    } catch {
      // Ignore JSON parse failures for non-JSON error responses.
    }
    throw new Error(`Request failed: ${response.status}${detail}`);
  }

  return (await response.json()) as T;
}

async function postJson<T>(path: string, body: unknown, baseUrl = apiBaseUrl()): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    let detail = "";
    try {
      const errorPayload = (await response.json()) as { detail?: unknown };
      if (typeof errorPayload.detail === "string") {
        detail = ` - ${errorPayload.detail}`;
      }
    } catch {
      // Ignore JSON parse failures for non-JSON error responses.
    }
    throw new Error(`Request failed: ${response.status}${detail}`);
  }

  return (await response.json()) as T;
}

async function patchJson<T>(path: string, body: unknown, baseUrl = apiBaseUrl()): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    let detail = "";
    try {
      const errorPayload = (await response.json()) as { detail?: unknown };
      if (typeof errorPayload.detail === "string") {
        detail = ` - ${errorPayload.detail}`;
      }
    } catch {
      // Ignore JSON parse failures for non-JSON error responses.
    }
    throw new Error(`Request failed: ${response.status}${detail}`);
  }

  return (await response.json()) as T;
}

export async function fetchBackendHealth(baseUrl = apiBaseUrl()): Promise<HealthResponse> {
  try {
    return await fetchJson<HealthResponse>("/health", baseUrl);
  } catch (error) {
    const message = error instanceof Error ? error.message.replace("Request failed", "Backend health request failed") : "Backend health request failed";
    throw new Error(message);
  }
}

export async function fetchDataManagerBusinesses(baseUrl = apiBaseUrl()): Promise<BusinessListItem[]> {
  const payload = await fetchJson<{ items: BusinessListItem[] }>("/data-manager/businesses", baseUrl);
  return payload.items;
}

export async function fetchDataManagerBusiness(
  businessName: string,
  baseUrl = apiBaseUrl()
): Promise<BusinessDetail> {
  return fetchJson<BusinessDetail>(`/data-manager/businesses/${encodeURIComponent(businessName)}`, baseUrl);
}

export async function fetchDataManagerCampaigns(
  businessName: string,
  baseUrl = apiBaseUrl()
): Promise<CampaignListItem[]> {
  const payload = await fetchJson<{ items: CampaignListItem[] }>(
    `/data-manager/businesses/${encodeURIComponent(businessName)}/campaigns`,
    baseUrl
  );
  return payload.items;
}

export async function fetchDataManagerCampaignDetail(
  businessName: string,
  campaignName: string,
  qualifier?: string | null,
  baseUrl = apiBaseUrl()
): Promise<CampaignDetailResponse> {
  const query = qualifier ? `?qualifier=${encodeURIComponent(qualifier)}` : "";
  return fetchJson<CampaignDetailResponse>(
    `/data-manager/businesses/${encodeURIComponent(businessName)}/campaigns/${encodeURIComponent(campaignName)}${query}`,
    baseUrl
  );
}

export async function saveCampaign(
  campaignId: number,
  commitMessage?: string,
  baseUrl = apiBaseUrl()
): Promise<CampaignSaveResponse> {
  const response = await fetch(`${baseUrl}/campaigns/${campaignId}/save`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({ commit_message: commitMessage?.trim() || undefined }),
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return (await response.json()) as CampaignSaveResponse;
}

export type ArtifactItem = {
  id: number;
  campaign_id: number;
  artifact_type: string;
  file_path: string;
  checksum: string;
  status: string;
  created_at: string | null;
};

export async function renderArtifact(
  campaignId: number,
  artifactType: "flyer" | "poster" = "flyer",
  baseUrl = apiBaseUrl()
): Promise<ArtifactItem> {
  const response = await fetch(`${baseUrl}/campaigns/${campaignId}/render`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({ artifact_type: artifactType }),
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return (await response.json()) as ArtifactItem;
}

export async function fetchArtifacts(
  campaignId: number,
  baseUrl = apiBaseUrl()
): Promise<ArtifactItem[]> {
  const payload = await fetchJson<{ items: ArtifactItem[] }>(
    `/campaigns/${campaignId}/artifacts`,
    baseUrl
  );
  return payload.items;
}

export function artifactDownloadUrl(artifactId: number, baseUrl = apiBaseUrl()): string {
  return `${baseUrl}/artifacts/${artifactId}/download`;
}

export async function listBusinesses(baseUrl = apiBaseUrl()): Promise<BusinessRecord[]> {
  return fetchJson<BusinessRecord[]>("/businesses", baseUrl);
}

export async function createBusiness(
  payload: Pick<BusinessRecord, "legal_name" | "display_name" | "timezone">,
  baseUrl = apiBaseUrl()
): Promise<BusinessRecord> {
  return postJson<BusinessRecord>("/businesses", payload, baseUrl);
}

export async function updateBusiness(
  businessId: number,
  payload: Partial<Pick<BusinessRecord, "legal_name" | "display_name" | "timezone" | "is_active">>,
  baseUrl = apiBaseUrl()
): Promise<BusinessRecord> {
  return patchJson<BusinessRecord>(`/businesses/${businessId}`, payload, baseUrl);
}

export async function listCampaignsForBusiness(
  businessId: number,
  baseUrl = apiBaseUrl()
): Promise<CampaignRecord[]> {
  const payload = await fetchJson<{ items: CampaignRecord[] }>(`/businesses/${businessId}/campaigns`, baseUrl);
  return payload.items;
}

export async function createCampaignForBusiness(
  businessId: number,
  payload: {
    campaign_name: string;
    campaign_key?: string;
    title: string;
    objective?: string;
    status?: string;
    start_date?: string;
    end_date?: string;
  },
  baseUrl = apiBaseUrl()
): Promise<CampaignRecord> {
  return postJson<CampaignRecord>(`/businesses/${businessId}/campaigns`, payload, baseUrl);
}

export async function lookupCampaigns(
  businessId: number,
  campaignName: string,
  baseUrl = apiBaseUrl()
): Promise<CampaignLookupResponse> {
  return fetchJson<CampaignLookupResponse>(
    `/businesses/${businessId}/campaigns/lookup?campaign_name=${encodeURIComponent(campaignName)}`,
    baseUrl
  );
}

export async function createChatSession(baseUrl = apiBaseUrl()): Promise<ChatSessionResponse> {
  return postJson<ChatSessionResponse>("/chat/sessions", {}, baseUrl);
}

export async function postChatMessage(
  sessionId: string,
  campaignId: number,
  message: string,
  baseUrl = apiBaseUrl()
): Promise<ChatMessageResponse> {
  return postJson<ChatMessageResponse>(
    `/chat/sessions/${encodeURIComponent(sessionId)}/messages`,
    { campaign_id: campaignId, message },
    baseUrl
  );
}

export async function syncYamlData(baseUrl = apiBaseUrl()): Promise<DataSyncResponse> {
  return postJson<DataSyncResponse>("/data/sync", {}, baseUrl);
}
