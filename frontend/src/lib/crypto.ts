import { beginCell, Cell, Address, toNano } from '@ton/core'
import { PAYMENT_OPCODE, RATING_OPCODE } from '../config'

const JETTON_TRANSFER_OPCODE = 0x0F8A7EA5

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

/**
 * Build jetton transfer payload for USDT payments.
 * Sent TO the user's jetton wallet, which forwards tokens to the agent.
 */
export function buildJettonTransferPayload(
  destinationAddress: string,
  jettonAmount: bigint,
  nonce: string,
  responseAddress: string,
): string {
  const forwardPayload = beginCell()
    .storeUint(PAYMENT_OPCODE, 32)
    .storeStringTail(nonce)
    .endCell()

  const cell = beginCell()
    .storeUint(JETTON_TRANSFER_OPCODE, 32)
    .storeUint(0, 64)                                      // query_id
    .storeCoins(jettonAmount)                               // amount
    .storeAddress(Address.parse(destinationAddress))         // destination (agent wallet)
    .storeAddress(Address.parse(responseAddress))            // response_destination (user, for excess)
    .storeBit(false)                                        // no custom_payload
    .storeCoins(toNano('0.000000001'))                      // forward_ton_amount (1 nanoton — minimal)
    .storeBit(true)                                         // forward_payload as ref
    .storeRef(forwardPayload)
    .endCell()
  return cell.toBoc().toString('base64')
}

/**
 * Resolve user's jetton wallet address by calling get_wallet_address on the master contract.
 * Uses Toncenter v3 API.
 */
export async function resolveJettonWallet(
  toncenterBase: string,
  jettonMaster: string,
  ownerAddress: string,
): Promise<string> {
  const ownerCell = beginCell()
    .storeAddress(Address.parse(ownerAddress))
    .endCell()
  const ownerBoc = ownerCell.toBoc().toString('base64')

  const resp = await fetch(
    `${toncenterBase}/runGetMethod`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        address: jettonMaster,
        method: 'get_wallet_address',
        stack: [{ type: 'slice', value: ownerBoc }],
      }),
    },
  )
  const data = await resp.json()
  const resultCell = Cell.fromBase64(data.stack[0].value)
  const addr = resultCell.beginParse().loadAddress()
  return addr.toString({ bounceable: true, urlSafe: true })
}

// Build on-chain rating payload tied to a specific sidecar + payment nonce
export function buildRatingPayload(sidecarId: string, nonce: string, score: number): string {
  const cell = beginCell()
    .storeUint(RATING_OPCODE, 32)
    .storeStringTail(`sidecar:${sidecarId} nonce:${nonce} score:${score}`)
    .endCell()
  return cell.toBoc().toString('base64')
}
