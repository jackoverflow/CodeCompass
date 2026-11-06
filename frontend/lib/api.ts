/**
 * Typed client for the CodeCompass FastAPI backend.
 *
 * Every call funnels through `request()`, so error handling, JSON parsing and
 * the base URL live in exactly one place. Server errors are surfaced as
 * `ApiError` with the backend's `detail` message intact, which is what the
 * dashboard shows to the user.
 */

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

export type Severity = "low" | "medium" | "high" | "critical";

export interface Project {
  id: string;
  name: string;
  repository_url: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface Dependency {
  id: string;
  source_file: string;
  target_file: string;
  dependency_type: string;
}

export interface DebtItem {
  id: string;
  title: string;
  description: string | null;
  severity: Severity;
  category: string;
  file_path: string | null;
  line_number: number | null;
  proposed_fix: string | null;
}

export interface ProjectDetail extends Project {
  dependencies: Dependency[];
  debt_items: DebtItem[];
}

export interface ScanSummary {
  files_scanned: number;
  dependencies_found: number;
  debt_items_found: number;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function extractDetail(body: unknown): string | null {
  if (typeof body !== "object" || body === null) return null;

  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;

  // FastAPI validation errors: [{ loc: [...], msg: "..." }, ...]
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) =>
        typeof item === "object" && item !== null && "msg" in item
          ? String((item as { msg: unknown }).msg)
          : null,
      )
      .filter((msg): msg is string => Boolean(msg));
    if (messages.length > 0) return messages.join("; ");
  }

  return null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...init?.headers,
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      `Cannot reach the API at ${API_BASE_URL}. Is the backend running?`,
      0,
    );
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      extractDetail(body) ?? `Request failed with status ${response.status}`,
      response.status,
    );
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function createProject(
  name: string,
  url: string,
): Promise<Project> {
  return request<Project>("/projects/", {
    method: "POST",
    body: JSON.stringify({ name, repository_url: url }),
  });
}

export async function scanProject(
  projectId: string,
  directoryPath: string,
): Promise<ScanSummary> {
  return request<ScanSummary>(
    `/projects/${encodeURIComponent(projectId)}/scan`,
    {
      method: "POST",
      body: JSON.stringify({ directory_path: directoryPath }),
    },
  );
}

export async function getProjectDetails(
  projectId: string,
): Promise<ProjectDetail> {
  return request<ProjectDetail>(
    `/projects/${encodeURIComponent(projectId)}`,
  );
}
