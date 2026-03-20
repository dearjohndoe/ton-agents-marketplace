import { beginCell, Cell } from '@ton/core'
import { PAYMENT_OPCODE, RATING_OPCODE } from '../config'

// Build TON transaction payload with nonce as payment opcode
export function buildPaymentPayload(nonce: string): string {
  const cell = beginCell()
    .storeUint(PAYMENT_OPCODE, 32)        // payment opcode
    .storeStringTail(nonce)
    .endCell()
  return cell.toBoc().toString('base64')
}

// Hash of the external message cell (hex) — used as a dedup key on the backend.
export function bocToMsgHash(boc: string): string {
  const bytes = Cell.fromBase64(boc).hash()
  return Array.from(bytes as unknown as Uint8Array).map(b => b.toString(16).padStart(2, '0')).join('')
}

// Build on-chain rating payload tied to a specific sidecar + payment nonce
export function buildRatingPayload(sidecarId: string, nonce: string, score: number): string {
  const cell = beginCell()
    .storeUint(RATING_OPCODE, 32)
    .storeStringTail(`sidecar:${sidecarId} nonce:${nonce} score:${score}`)
    .endCell()
  return cell.toBoc().toString('base64')
}
