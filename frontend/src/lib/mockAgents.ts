import type { Agent } from '../types'

export const MOCK_AGENTS: Agent[] = [
  // ── TON only (existing behavior) ──
  {
    sidecarId: 'mock-1',
    address: 'EQBvW8Z5huBkMJYdnfAEM5JqTNkuWX3diqYENkWsIL0XggGG',
    name: 'Translator Agent',
    description: 'Translates text between 100+ languages. Priced in TON only.',
    capabilities: ['translate'],
    price: 10000000,
    endpoint: 'https://translator.example.com',
    argsSchema: {
      text: { type: 'string', description: 'Text to translate', required: true },
      target_lang: { type: 'string', description: 'Target language code (en, ru, de…)', required: false },
    },
    lastHeartbeat: Math.floor(Date.now() / 1000) - 120,
  },

  // ── USDT only ──
  {
    sidecarId: 'mock-2',
    address: 'EQDtFpEwcFAEcRe5mLVh2N6C2theRSmP5NFp6x61ZygPk4En',
    name: 'Image Generator',
    description: 'Generates images from text prompts. Priced in USDT only.',
    capabilities: ['generate_image'],
    price: 0,
    priceUsdt: 500000, // 0.5 USDT
    endpoint: 'http://94.130.22.17:8080',
    argsSchema: {
      prompt: { type: 'string', description: 'Image description', required: true },
      style: { type: 'string', description: 'Art style (realistic, anime, etc.)', required: false },
    },
    lastHeartbeat: Math.floor(Date.now() / 1000) - 60,
  },

  // ── Both TON + USDT ──
  {
    sidecarId: 'mock-3',
    address: 'EQCkR1cGmwhNorL6jTA9OgDkgStRuACBkMxEMfbkIkNX0EK3',
    name: 'Orchestrator',
    description: 'Breaks down complex tasks, coordinates multiple agents. Accepts TON or USDT.',
    capabilities: ['orchestrate'],
    price: 100000000, // 0.1 TON
    priceUsdt: 1000000, // 1 USDT
    endpoint: 'http://192.168.1.50:3000',
    argsSchema: {
      task: { type: 'string', description: 'Task description', required: true },
    },
    lastHeartbeat: Math.floor(Date.now() / 1000) - 1800,
    hasQuote: true,
  },

  // ── TON only, cheap ──
  {
    sidecarId: 'mock-4',
    address: 'EQB3ncyBUTjZUA5EnFKR5_EnOMI9V1tTeDShu7XFBN3Eaacq',
    name: 'Summarizer',
    description: 'Summarizes long documents. TON only, low price.',
    capabilities: ['summarize'],
    price: 8000000,
    endpoint: 'https://summarizer.example.com',
    argsSchema: {
      text: { type: 'string', description: 'Text to summarize', required: true },
      max_length: { type: 'number', description: 'Max summary length in words', required: false },
    },
    lastHeartbeat: Math.floor(Date.now() / 1000) - 5400,
  },

  // ── Both TON + USDT, no quote ──
  {
    sidecarId: 'mock-5',
    address: 'EQA0i8-CdGnF_DhUHHf92R1ONH6sIA9vLZ_WLcCIhfBBXwtG',
    name: 'Code Assistant',
    description: 'Writes, reviews and debugs code. Accepts both TON and USDT.',
    capabilities: ['write_code'],
    price: 30000000, // 0.03 TON
    priceUsdt: 100000, // 0.1 USDT
    endpoint: 'http://agent.dev.local:8080',
    argsSchema: {
      task: { type: 'string', description: 'What to code', required: true },
      language: { type: 'string', description: 'Programming language', required: false },
    },
    lastHeartbeat: Math.floor(Date.now() / 1000) - 200,
  },

  // ── USDT only, with quote ──
  {
    sidecarId: 'mock-6',
    address: 'EQBvW8Z5huBkMJYdnfAEM5JqTNkuWX3diqYENkWsIL0XggGG',
    name: 'Audio Transcriber',
    description: 'Transcribes audio files to text. USDT only, with dynamic pricing.',
    capabilities: ['transcribe'],
    price: 0,
    priceUsdt: 2000000, // 2 USDT
    endpoint: 'https://transcriber.example.com',
    argsSchema: {
      audio_url: { type: 'string', description: 'URL of the audio file to transcribe', required: true },
      language: { type: 'string', description: 'Language hint (e.g. en, ru)', required: false },
    },
    lastHeartbeat: Math.floor(Date.now() / 1000) - 90,
    hasQuote: true,
    resultSchema: { type: 'string' },
  },

  // ── Both TON + USDT, expensive ──
  {
    sidecarId: 'mock-7',
    address: 'EQBvW8Z5huBkMJYdnfAEM5JqTNkuWX3diqYENkWsIL0XggGG',
    name: 'PDF Generator',
    description: 'Renders HTML/markdown into PDF. Both TON and USDT, higher price.',
    capabilities: ['generate_pdf'],
    price: 500000000, // 0.5 TON
    priceUsdt: 5000000, // 5 USDT
    endpoint: 'http://94.130.22.17:8081',
    argsSchema: {
      content: { type: 'string', description: 'HTML or markdown content to render', required: true },
    },
    lastHeartbeat: Math.floor(Date.now() / 1000) - 45,
    resultSchema: { type: 'file', mime_type: 'application/pdf' },
  },

  // ── USDT only, micro price ──
  {
    sidecarId: 'mock-8',
    address: 'EQCkR1cGmwhNorL6jTA9OgDkgStRuACBkMxEMfbkIkNX0EK3',
    name: 'Sentiment Analyzer',
    description: 'Analyzes text sentiment. USDT only, very cheap.',
    capabilities: ['sentiment'],
    price: 0,
    priceUsdt: 10000, // 0.01 USDT
    endpoint: 'https://sentiment.example.com',
    argsSchema: {
      text: { type: 'string', description: 'Text to analyze', required: true },
    },
    lastHeartbeat: Math.floor(Date.now() / 1000) - 300,
  },
]
