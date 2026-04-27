export type HealthResponse = {
  status: string;
  database: string;
  output_dir: string;
};

export function apiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}

export async function fetchBackendHealth(baseUrl = apiBaseUrl()): Promise<HealthResponse> {
  const response = await fetch(`${baseUrl}/health`, {
    method: "GET",
    headers: {
      Accept: "application/json",
    },
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`Backend health request failed: ${response.status}`);
  }

  return (await response.json()) as HealthResponse;
}
