import type { Agent } from '../../../types'

export function buildBody(
  fields: Record<string, string>,
  argsSchema: Agent['argsSchema'],
): Record<string, string | number | boolean> {
  const body: Record<string, string | number | boolean> = {}
  for (const [k, v] of Object.entries(fields)) {
    const s = argsSchema[k]
    if (!s || s.type === 'file') continue
    body[k] = s.type === 'number' ? Number(v) : s.type === 'boolean' ? v === 'true' : v
  }
  return body
}
