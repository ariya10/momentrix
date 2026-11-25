import React from 'react'
import { createRoot } from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import './styles/studio.css'

const client = new QueryClient({ defaultOptions: { queries: { staleTime: 2000, retry: false } } })
createRoot(document.getElementById('root')!).render(
  <React.StrictMode><QueryClientProvider client={client}><HashRouter><App/></HashRouter></QueryClientProvider></React.StrictMode>
)
