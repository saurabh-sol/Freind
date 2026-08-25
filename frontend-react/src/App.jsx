import React, { useState, useEffect } from 'react'
import { Analytics } from '@vercel/analytics/react'
import GuestView from './components/GuestView'
import AdminView from './components/AdminView'

function App() {
  const [currentPath, setCurrentPath] = useState(window.location.pathname)

  useEffect(() => {
    const handleLocationChange = () => {
      setCurrentPath(window.location.pathname)
    }
    window.addEventListener('popstate', handleLocationChange)
    return () => {
      window.removeEventListener('popstate', handleLocationChange)
    }
  }, [])

  const navigate = (path) => {
    window.history.pushState({}, '', path)
    setCurrentPath(path)
  }

  // Handle SPA routing
  if (currentPath.startsWith('/admin')) {
    return (
      <>
        <AdminView navigate={navigate} />
        <Analytics />
      </>
    )
  }

  return (
    <>
      <GuestView navigate={navigate} />
      <Analytics />
    </>
  )
}

export default App
