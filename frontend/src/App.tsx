import './App.css'

function App() {
  return (
    <div className="app">
      <header className="header">
        <h1 className="logo">
          <span className="logo-fin">Fin</span>
          <span className="logo-sight">Sight</span>
        </h1>
      </header>

      <main className="main">
        <div className="search-container">
          <input
            type="text"
            className="search-input"
            placeholder='Search a company or drop a filing...'
            disabled
          />
          <p className="search-hint">
            Type "Apple" or "AAPL" for instant analysis. Drop a PDF for deep document analysis.
          </p>
        </div>
      </main>

      <footer className="footer">
        <p>Financial intelligence powered by SEC EDGAR and document RAG</p>
      </footer>
    </div>
  )
}

export default App
