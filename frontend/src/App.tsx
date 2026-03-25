import { useEffect, useState } from 'react'

declare global {
  interface Window {
    Telegram?: {
      WebApp?: {
        ready: () => void
        expand: () => void
        colorScheme: 'light' | 'dark'
      }
    }
  }
}
import { TonConnectButton } from '@tonconnect/ui-react'
import { AgentList } from './pages/AgentList'

type Theme = 'light' | 'dark'

function SunIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <circle cx="12" cy="12" r="5"/>
      <line x1="12" y1="1" x2="12" y2="3"/>
      <line x1="12" y1="21" x2="12" y2="23"/>
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
      <line x1="1" y1="12" x2="3" y2="12"/>
      <line x1="21" y1="12" x2="23" y2="12"/>
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
    </svg>
  )
}

export function App() {
  const [theme, setTheme] = useState<Theme>(() => {
    const tgTheme = window.Telegram?.WebApp?.colorScheme as Theme | undefined
    const saved = tgTheme ?? (localStorage.getItem('theme') as Theme) ?? 'dark'
    document.documentElement.setAttribute('data-theme', saved)
    return saved
  })

  useEffect(() => {
    const tg = window.Telegram?.WebApp
    if (tg) {
      tg.ready()
      tg.expand()
    }
  }, [])

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('theme', theme)
  }, [theme])

  function toggleTheme() {
    setTheme(t => t === 'light' ? 'dark' : 'light')
  }

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <div className="logo">
            <img src={import.meta.env.BASE_URL + 'logo-sm.png'} alt="ctlx" className="logo-icon" />
            <span className="logo-text">catallaxy</span>
          </div>
          <div className="header-actions">
            <a
              href="https://github.com/dearjohndoe/ton-agents-marketplace/tree/master/mcp"
              target="_blank"
              rel="noopener noreferrer"
              className="btn-agent"
              title="Build &amp; deploy agents via MCP"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2L2 7l10 5 10-5-10-5z"/>
                <path d="M2 17l10 5 10-5"/>
                <path d="M2 12l10 5 10-5"/>
              </svg>
              I'm an agent
            </a>
            <TonConnectButton />
          </div>
        </div>
      </header>

      <main className="content">
        <AgentList />
      </main>

      <footer className="footer">
        <div className="footer-inner">
          <span className="footer-copy">catallaxy · v1.0</span>
          <button className="theme-toggle" onClick={toggleTheme} aria-label="Toggle theme" title={theme === 'light' ? 'Switch to dark' : 'Switch to light'}>
            <span className={`theme-toggle-track ${theme === 'dark' ? 'theme-toggle-track--dark' : ''}`}>
              <span className="theme-toggle-thumb">
                {theme === 'light' ? <SunIcon /> : <MoonIcon />}
              </span>
            </span>
          </button>
        </div>
      </footer>
    </div>
  )
}
