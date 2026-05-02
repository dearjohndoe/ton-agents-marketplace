import type { SidecarFixture, PersistedAgentState } from './types'
import { PERSIST_KEY } from './constants'
import { AgentState } from './AgentState'
import { readPersisted, writePersisted } from './persistence'

export class MockSidecarBackend {
  private byEndpoint = new Map<string, AgentState>()
  private fixtures: SidecarFixture[]

  constructor(fixtures: SidecarFixture[]) {
    this.fixtures = fixtures
    const persisted = readPersisted()
    const onPersist = () => this.persist()
    for (const fx of fixtures) {
      const state = new AgentState(fx, onPersist)
      const snapshot = persisted[fx.sidecarId]
      if (snapshot) state.hydrate(snapshot)
      this.byEndpoint.set(fx.endpoint, state)
    }
  }

  private persist() {
    const map: Record<string, PersistedAgentState> = {}
    for (const a of this.byEndpoint.values()) map[a.fx.sidecarId] = a.serialize()
    writePersisted(map)
  }

  resolve(url: string): AgentState | null {
    try {
      const u = new URL(url)
      const origin = `${u.protocol}//${u.host}`
      return this.byEndpoint.get(origin) ?? null
    } catch {
      return null
    }
  }

  resolveByEndpoint(endpoint: string): AgentState | null {
    return this.byEndpoint.get(endpoint) ?? null
  }

  list() { return [...this.byEndpoint.values()] }
  fixturesList() { return this.fixtures }
  reset() {
    for (const a of this.byEndpoint.values()) a.reset()
    if (typeof localStorage !== 'undefined') {
      try { localStorage.removeItem(PERSIST_KEY) } catch {}
    }
  }
}
