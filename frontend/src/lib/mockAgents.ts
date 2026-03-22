import type { Agent } from '../types'

export const MOCK_AGENTS: Agent[] = [
  {
    sidecarId: 'mock-1',
    address: 'EQBvW8Z5huBkMJYdnfAEM5JqTNkuWX3diqYENkWsIL0XggGG',
    name: 'Translator Agent',
    description: 'Translates text between 100+ languages using advanced AI models.',
    capabilities: ['translate'],
    price: 10000000,
    endpoint: 'https://translator.example.com',
    argsSchema: {
      text: { type: 'string', description: 'Text to translate', required: true },
      target_lang: { type: 'string', description: 'Target language code (en, ru, de…)', required: false },
    },
    lastHeartbeat: Math.floor(Date.now() / 1000) - 120,
  },
  {
    sidecarId: 'mock-2',
    address: 'EQDtFpEwcFAEcRe5mLVh2N6C2theRSmP5NFp6x61ZygPk4En',
    name: 'Image Generator',
    description: 'Generates high-quality images from text prompts.',
    capabilities: ['generate_image'],
    price: 50000000,
    endpoint: 'http://94.130.22.17:8080',
    argsSchema: {
      prompt: { type: 'string', description: 'Image description', required: true },
      style: { type: 'string', description: 'Art style (realistic, anime, etc.)', required: false },
    },
    lastHeartbeat: Math.floor(Date.now() / 1000) - 60,
  },
  {
    sidecarId: 'mock-3',
    address: 'EQCkR1cGmwhNorL6jTA9OgDkgStRuACBkMxEMfbkIkNX0EK3',
    name: 'Orchestrator',
    description: 'Breaks down complex tasks and coordinates multiple agents to complete them.',
    capabilities: ['orchestrate'],
    price: 100000000,
    endpoint: 'http://192.168.1.50:3000',
    argsSchema: {
      task: { type: 'string', description: 'Task description', required: true },
    },
    lastHeartbeat: Math.floor(Date.now() / 1000) - 1800,
    hasQuote: true,
  },
  {
    sidecarId: 'mock-4',
    address: 'EQB3ncyBUTjZUA5EnFKR5_EnOMI9V1tTeDShu7XFBN3Eaacq',
    name: 'Summarizer',
    description: 'Summarizes long documents, articles and web pages into concise key points.',
    capabilities: ['summarize'],
    price: 8000000,
    endpoint: 'https://summarizer.example.com',
    argsSchema: {
      text: { type: 'string', description: 'Text to summarize', required: true },
      max_length: { type: 'number', description: 'Max summary length in words', required: false },
    },
    lastHeartbeat: Math.floor(Date.now() / 1000) - 5400,
  },
  {
    sidecarId: 'mock-5',
    address: 'EQA0i8-CdGnF_DhUHHf92R1ONH6sIA9vLZ_WLcCIhfBBXwtG',
    name: 'Code Assistant',
    description: 'Writes, reviews and debugs code in 50+ programming languages.',
    capabilities: ['write_code'],
    price: 30000000,
    endpoint: 'http://agent.dev.local:8080',
    argsSchema: {
      task: { type: 'string', description: 'What to code', required: true },
      language: { type: 'string', description: 'Programming language', required: false },
    },
    lastHeartbeat: Math.floor(Date.now() / 1000) - 200,
  },
]
