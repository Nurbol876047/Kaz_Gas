let csrfToken = "";
export function setCsrfToken(token: string) {
  csrfToken = token;
}
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body) headers.set("Content-Type", "application/json");
  if (options.method && !["GET", "HEAD"].includes(options.method))
    headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch(`/api${path}`, {
    ...options,
    headers,
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail =
      typeof body.detail === "string"
        ? body.detail
        : body.detail?.map((e: { msg: string }) => e.msg).join("; ");
    if (
      response.status === 401 &&
      path !== "/auth/login" &&
      path !== "/auth/me"
    )
      window.dispatchEvent(new Event("session-expired"));
    throw new ApiError(
      response.status,
      detail || "Сұраныс орындалмады. Қайта көріңіз.",
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export async function downloadImportTemplate() {
  const response = await fetch("/api/subscribers/import/template", {
    credentials: "same-origin",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "Үлгіні жүктеу орындалмады");
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = "abonentter_ulgisi.xlsx";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export async function downloadSubscribersExport(format: "csv" | "xlsx") {
  const response = await fetch(`/api/subscribers/export?format=${format}`, {
    credentials: "same-origin",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "Экспорт орындалмады");
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = `abonentter.${format}`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export type ImportResult = {
  created: number;
  total: number;
  skipped: { line: number; reason: string }[];
  errors: { line: number; reason: string }[];
};
export async function importSubscribers(file: File): Promise<ImportResult> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/api/subscribers/import", {
    method: "POST",
    body: form,
    headers: { "X-CSRF-Token": csrfToken },
    credentials: "same-origin",
    cache: "no-store",
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail =
      typeof body.detail === "string"
        ? body.detail
        : body.detail?.map((e: { msg: string }) => e.msg).join("; ");
    throw new ApiError(response.status, detail || "Импорт орындалмады");
  }
  return body;
}
export async function downloadReport(query: string, format: "csv" | "xlsx") {
  const response = await fetch(
    `/api/reports/export?${query}&format=${format}`,
    { credentials: "same-origin" },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "Экспорт орындалмады");
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = `applications.${format}`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
