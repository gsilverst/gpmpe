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
    throw new Error(`Request failed: ${response.status}`);
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
