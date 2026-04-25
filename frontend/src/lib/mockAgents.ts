import { FIXTURES } from '../mocks/fixtures'
import type { Agent } from '../types'

/**
 * In mock mode, agents are derived from MSW fixtures so that the on-chain
 * registry view (cards in the marketplace) and the live HTTP responses
 * (/info, /quote, /invoke) come from a single source of truth.
 */
export const MOCK_AGENTS: Agent[] = FIXTURES.map(fx => {
  const headSku = fx.skus[0]
  return {
    sidecarId: fx.sidecarId,
    address: fx.agent.address,
    name: fx.agent.name,
    description: fx.agent.description,
    capabilities: fx.agent.capabilities,
    price: headSku.priceTon ?? 0,
    priceUsdt: headSku.priceUsdt,
    endpoint: fx.endpoint,
    argsSchema: fx.agent.argsSchema,
    lastHeartbeat: Math.floor(Date.now() / 1000) - 60,
    hasQuote: fx.agent.hasQuote,
    resultSchema: fx.agent.resultSchema,
    previewUrl: fx.agent.previewUrl,
    avatarUrl: fx.agent.avatarUrl,
    images: fx.agent.images,
  }
})
