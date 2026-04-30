import { Address } from '@ton/core'
import { TESTNET } from '../../config'

export function nanoToTon(n: number) {
  const t = n / 1e9
  return t < 0.001 ? t.toExponential(2) : t.toFixed(3).replace(/\.?0+$/, '')
}

export function microToUsdt(n: number) {
  const t = n / 1e6
  return t < 0.01 ? t.toExponential(2) : t.toFixed(2).replace(/\.?0+$/, '')
}

export function formatAddr(raw: string): string {
  try {
    const friendly = Address.parse(raw).toString({ bounceable: false, urlSafe: true, testOnly: TESTNET })
    return `${friendly.slice(0, 7)}…${friendly.slice(-7)}`
  } catch {
    return `${raw.slice(0, 7)}…${raw.slice(-7)}`
  }
}

export function friendlyAddr(raw: string): string {
  try {
    return Address.parse(raw).toString({ bounceable: false, urlSafe: true, testOnly: TESTNET })
  } catch {
    return raw
  }
}

export function normalizeDesc(s: string): string {
  return s.replace(/\\n/g, '\n')
}
