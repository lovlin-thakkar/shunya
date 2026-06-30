const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const API_KEY_STORAGE = "shunya_api_key";

function getApiKey(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(API_KEY_STORAGE) ?? "";
}

function headers(): HeadersInit {
  const key = getApiKey();
  return {
    "Content-Type": "application/json",
    ...(key ? { Authorization: `Api-Key ${key}` } : {}),
  };
}

export async function apiFetch<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: { ...headers(), ...(options?.headers ?? {}) },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  if (res.status === 204 || res.headers.get("content-length") === "0") {
    return undefined as unknown as T;
  }
  return res.json() as Promise<T>;
}

export const swrFetcher = <T>(url: string) => apiFetch<T>(url);

/**
 * Fetch a run's WAV recording through the authenticated, tenant-scoped endpoint
 * and return an object URL suitable for an <audio> src / download link.
 *
 * The browser's <audio> tag can't send the Api-Key header, so we fetch the bytes
 * with auth here and hand back a blob URL. Callers must URL.revokeObjectURL() it
 * when done to avoid leaking memory.
 */
export async function fetchRecordingBlobUrl(runId: string): Promise<string> {
  const key = getApiKey();
  const res = await fetch(`${API_URL}/api/v1/test-runs/${runId}/recording/`, {
    headers: key ? { Authorization: `Api-Key ${key}` } : {},
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return URL.createObjectURL(await res.blob());
}
