export type CallStatus =
  | 'idle' | 'quoting' | 'quoted' | 'paying'
  | 'invoking' | 'polling' | 'done' | 'error'
  | 'refunded'

export type FlowResult<T> =
  | { kind: 'ok'; value: T }
  | { kind: 'error'; message: string }
