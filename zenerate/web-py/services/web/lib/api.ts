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
  return res.json() as Promise<T>;
}

export const swrFetcher = <T>(url: string) => apiFetch<T>(url);

export function recordingUrl(runId: string): string {
  return `${API_URL}/recordings/${runId}.wav`;
}
