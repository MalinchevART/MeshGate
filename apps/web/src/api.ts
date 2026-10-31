// API клиент — cookie сесия; base '' (същият произход през Traefik, /api се реже)
export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (r.status === 401) throw new Unauthorized()
  const body = await r.json().catch(() => ({}))
  if (!r.ok) throw new ApiError(body?.error?.message || r.statusText, r.status, body?.error?.code)
  return body.data ?? body
}

export class ApiError extends Error {
  code?: string
  status: number
  constructor(message: string, status: number, code?: string) {
    super(message)
    this.status = status
    this.code = code
  }
}
export class Unauthorized extends Error {}

export function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('bg-BG')
}
