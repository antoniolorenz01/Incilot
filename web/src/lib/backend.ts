// Solo en el servidor (lo importan las rutas /api): las URLs nunca llegan al navegador.

const INJECTOR_URL = process.env.INJECTOR_URL ?? "http://localhost:8100";
const AGENT_API_URL = process.env.AGENT_API_URL ?? "http://localhost:8200";
const PROMETHEUS_URL = process.env.PROMETHEUS_URL ?? "http://localhost:9090";

export function injector(path: string, init?: RequestInit) {
  return fetch(`${INJECTOR_URL}${path}`, { cache: "no-store", ...init });
}

export function agent(path: string, init?: RequestInit) {
  return fetch(`${AGENT_API_URL}${path}`, { cache: "no-store", ...init });
}

export function prometheus(path: string) {
  return fetch(`${PROMETHEUS_URL}${path}`, { cache: "no-store" });
}

export const json = { "content-type": "application/json" };

/** Reenvía la respuesta de un servicio tal cual (status y cuerpo JSON). */
export async function relay(response: Response) {
  const body = await response.text();
  return new Response(body, { status: response.status, headers: json });
}
