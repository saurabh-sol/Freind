import React, { useState, useEffect } from 'react'
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
    return <AdminView navigate={navigate} />
  }

  return <GuestView navigate={navigate} />
}

export default App
