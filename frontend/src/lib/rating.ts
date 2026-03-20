import axios from 'axios'
import { Cell } from '@ton/core'
import {
  TONCENTER_BASE,
  TX_PAGE_SIZE,
  PAYMENT_OPCODE,
  REFUND_OPCODE,
  RATING_OPCODE,
  MIN_RATING_TXS,
} from '../config'

const PAYMENT_HEX = `0x${PAYMENT_OPCODE.toString(16)}`
const REFUND_HEX = `0x${REFUND_OPCODE.toString(16)}`
const RATING_HEX = `0x${RATING_OPCODE.toString(16)}`

export interface OnChainRating {
  score: number | null
  totalTxs: number
  reviews: number
  status: 'ready' | 'new' | 'empty'
}

interface ClassifiedTx {
  type: 'payment' | 'refund' | 'review'
  weight: number
}

function classifyTx(tx: any, sidecarId: string): ClassifiedTx | null {
  const inMsg = tx.in_msg

  if (inMsg?.opcode) {
    const opcode = inMsg.opcode.toLowerCase()

    // Payment: parse nonce from body, verify it ends with :{sidecarId}
    if (opcode === PAYMENT_HEX) {
      try {
        const body = inMsg?.message_content?.body
        if (!body) return null
        const slice = Cell.fromBase64(body).beginParse()
        slice.loadUint(32)
        const nonce = slice.loadStringTail()
        if (!nonce.includes(`:${sidecarId}`)) return null
        return { type: 'payment', weight: 2.0 }
      } catch {
        return null
      }
    }

    // Rating: payload contains sidecar:{sidecarId} and score
    if (opcode === RATING_HEX) {
      try {
        const body = inMsg?.message_content?.body
        if (!body) return null
        const slice = Cell.fromBase64(body).beginParse()
        slice.loadUint(32)
        const payload = slice.loadStringTail()
        if (!payload.includes(`sidecar:${sidecarId}`)) return null
        const match = payload.match(/score:(\d)/)
        if (!match) return null
        const userScore = parseInt(match[1], 10)
        if (userScore < 1 || userScore > 5) return null
        return { type: 'review', weight: (userScore - 3) * 1.25 }
      } catch {
        return null
      }
    }
  }

  // Refund: outgoing message with REFUND_OPCODE and matching sidecar_id in JSON body
  for (const outMsg of tx.out_msgs ?? []) {
    if (outMsg?.opcode?.toLowerCase() !== REFUND_HEX) continue
    try {
      const body = outMsg?.message_content?.body
      if (!body) continue
      const slice = Cell.fromBase64(body).beginParse()
      slice.loadUint(32)
      const parsed = JSON.parse(slice.loadStringTail())
      if (parsed.sidecar_id !== sidecarId) continue
      return { type: 'refund', weight: -2.1 }
    } catch {
      continue
    }
  }

  return null
}

export async function fetchOnChainRating(agentAddress: string, sidecarId: string): Promise<OnChainRating> {
  // Fetch incoming transactions to the agent address
  const { data: agentTxData } = await axios.get(`${TONCENTER_BASE}/transactions`, {
    params: {
      account: agentAddress,
      limit: TX_PAGE_SIZE,
      sort: 'desc',
    },
  })

  const agentTxs: any[] = agentTxData.transactions ?? []

  const classified: ClassifiedTx[] = []

  for (const tx of agentTxs) {
    const c = classifyTx(tx, sidecarId)
    if (c) classified.push(c)
  }

  const totalTxs = classified.length
  const reviews = classified.filter(c => c.type === 'review').length

  if (totalTxs === 0) {
    return { score: null, totalTxs: 0, reviews: 0, status: 'empty' }
  }

  if (totalTxs < MIN_RATING_TXS) {
    return { score: null, totalTxs, reviews, status: 'new' }
  }

  const rawScore = classified.reduce((sum, c) => sum + c.weight, 0)
  const maxPossible = totalTxs * 2.5
  const minPossible = totalTxs * -2.5

  const normalized = ((rawScore - minPossible) / (maxPossible - minPossible)) * 10
  const score = Math.round(Math.min(10, Math.max(0, normalized)) * 10) / 10

  return { score, totalTxs, reviews, status: 'ready' }
}
