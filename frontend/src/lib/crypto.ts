import { beginCell, Cell } from '@ton/core'

// Generates a random nonce with embedded sidecar ID
// Format: {uuid}:{sidecar_id}
export function generateNonce(sidecarId: string): string {
  const id = crypto.randomUUID()
  return `${id}:${sidecarId}`
}

// Build TON transaction payload with nonce as text comment
// Note: unencrypted for MVP — encryption via TON Connect wallet is a roadmap item
export function buildCommentPayload(nonce: string): string {
  const cell = beginCell()
    .storeUint(0, 32)        // text comment opcode
    .storeStringTail(nonce)
    .endCell()
  return cell.toBoc().toString('base64')
}

// Hash of the external message cell (hex) — used as a dedup key on the backend.
export function bocToMsgHash(boc: string): string {
  const bytes = Cell.fromBase64(boc).hash()
  return Array.from(bytes as unknown as Uint8Array).map(b => b.toString(16).padStart(2, '0')).join('')
}
