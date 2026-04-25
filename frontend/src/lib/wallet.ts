import { useTonConnectUI, useTonAddress } from '@tonconnect/ui-react'
import { Address, beginCell } from '@ton/core'

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'

// Generated at module load — guarantees valid checksum so `Address.parse`
// (called downstream in useAgentCall when building jetton transfers) works.
const MOCK_ADDRESS_FRIENDLY = new Address(0, Buffer.alloc(32, 0xab))
  .toString({ urlSafe: true, bounceable: false })

function buildFakeBoc(): string {
  // A minimal valid Cell — `bocToMsgHash` needs to call .hash() on it.
  return beginCell().storeUint(0xdeadbeef, 32).endCell().toBoc().toString('base64')
}

export interface WalletUI {
  sendTransaction: (params: any) => Promise<{ boc: string }>
  account?: { address: string } | null
}

const mockUI: WalletUI = {
  sendTransaction: async () => {
    // Tiny artificial delay so loading states are visible in the demo.
    await new Promise(r => setTimeout(r, 300))
    return { boc: buildFakeBoc() }
  },
  account: { address: MOCK_ADDRESS_FRIENDLY },
}

export function useWalletUI(): WalletUI {
  const [ui] = useTonConnectUI()
  if (USE_MOCK) return mockUI
  return ui as WalletUI
}

export function useWalletAddress(): string {
  const real = useTonAddress()
  if (USE_MOCK) return MOCK_ADDRESS_FRIENDLY
  return real
}
