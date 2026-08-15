'use client'

import { Suspense, useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'next/navigation'

const API = process.env.NEXT_PUBLIC_API_URL

// An anonymous, per-browser id. Lets you tell "five people rejected this"
// apart from "one person clicked it five times". Swap for a real user id
// when accounts land — the column already accepts one.
function getSessionId(): string {
  if (typeof window === 'undefined') return ''
  let id = window.localStorage.getItem('vv_session')
  if (!id) {
    id = crypto.randomUUID()
    window.localStorage.setItem('vv_session', id)
  }
  return id
}

interface Product {
  id: number
  name: string
  brand: string
  price: number
  image_url: string
  affiliate_url: string
  category: string
  gender: string
  similarity: number
}

const PRICE_PRESETS = [
  { label: 'Any price', min: null, max: null },
  { label: 'Under £25',  min: null, max: 25 },
  { label: '£25–£50',    min: 25,   max: 50 },
  { label: '£50–£100',   min: 50,   max: 100 },
  { label: 'Over £100',  min: 100,  max: null },
]

const GENDER_OPTIONS = [
  { label: 'All',     value: null },
  { label: "Women's", value: 'f' },
  { label: "Men's",   value: 'm' },
  { label: 'Unisex',  value: 'unisex' },
]

const SORT_OPTIONS = [
  { label: 'Most relevant', value: 'relevant' },
  { label: 'Price: low–high', value: 'price_asc' },
  { label: 'Price: high–low', value: 'price_desc' },
]

function ThumbUp() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="2" strokeLinecap="round"
         strokeLinejoin="round" aria-hidden="true">
      <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3" />
    </svg>
  )
}

function ThumbDown() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="2" strokeLinecap="round"
         strokeLinejoin="round" aria-hidden="true">
      <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17" />
    </svg>
  )
}

function SearchResults() {
  const searchParams = useSearchParams()
  const q = searchParams.get('q') || ''

  const [results, setResults] = useState<Product[]>([])
  const [loading, setLoading] = useState(false)
  const [gender, setGender] = useState<string | null>(null)
  const [pricePreset, setPricePreset] = useState(0)
  const [brand, setBrand] = useState<string | null>(null)
  const [sort, setSort] = useState('relevant')
  const [filtersOpen, setFiltersOpen] = useState(true)
  const [rating, setRating] = useState<'up' | 'down' | null>(null)
  const [dismissed, setDismissed] = useState<number[]>([])

  const fetchResults = useCallback(async () => {
    if (!q) return
    setLoading(true)
    const preset = PRICE_PRESETS[pricePreset]
    const url = new URL(`${API}/search`)
    url.searchParams.set('q', q)
    url.searchParams.set('limit', '100')
    if (gender) url.searchParams.set('gender', gender)
    if (preset.min) url.searchParams.set('price_min', String(preset.min))
    if (preset.max) url.searchParams.set('price_max', String(preset.max))
    if (brand) url.searchParams.set('brand', brand)
    try {
      const res = await fetch(url.toString(), { cache: 'no-store' })
      const data = await res.json()
      setResults(data.results || [])
    } catch {
      setResults([])
    } finally {
      setLoading(false)
    }
  }, [q, gender, pricePreset, brand])

  useEffect(() => {
    fetchResults()
  }, [fetchResults])

  // Ratings and dismissals belong to one query. New query, clean slate.
  useEffect(() => {
    setRating(null)
    setDismissed([])
  }, [q])

  function recordClick(productId: number) {
    if (!API || !q) return
    fetch(`${API}/click`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: q, product_id: productId }),
      keepalive: true,
    }).catch(() => {})
  }

  function recordRating(value: 'up' | 'down') {
    const next = rating === value ? null : value
    setRating(next)
    if (!API || !q || next === null) return
    fetch(`${API}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: q, rating: next === 'up' ? 1 : -1 }),
      keepalive: true,
    }).catch(() => {})
  }

  // Hide the card immediately, then tell the server. If the request fails
  // the card stays hidden — the person's screen should never argue with
  // them over a logging failure.
  function rejectProduct(productId: number) {
    setDismissed(prev => [...prev, productId])
    if (!API || !q) return
    fetch(`${API}/product-feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: q,
        product_id: productId,
        rating: -1,
        session_id: getSessionId(),
      }),
      keepalive: true,
    }).catch(() => {})
  }

  function undoReject(productId: number) {
    setDismissed(prev => prev.filter(id => id !== productId))
  }

  const seen = new Set<string>()
  const uniqueResults = results.filter(product => {
    const key = `${product.name.split('|')[0].trim()}-${product.brand}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })

  const sorted = [...uniqueResults].sort((a, b) => {
    if (sort === 'price_asc') return Number(a.price) - Number(b.price)
    if (sort === 'price_desc') return Number(b.price) - Number(a.price)
    return 0
  })

  const visible = sorted.filter(p => !dismissed.includes(p.id))
  const brands = Array.from(new Set(uniqueResults.map(p => p.brand))).sort()
  const showRating = !loading && sorted.length > 0
  const lastDismissed = dismissed[dismissed.length - 1]

  return (
    <main className="min-h-screen bg-black text-white">
      <div className="border-b border-zinc-800 px-6 py-4 flex flex-wrap items-center gap-4">
        <a href="/" className="text-zinc-500 text-xs tracking-widest uppercase font-mono hover:text-white transition-colors">
          VectorVibe
        </a>
        <form action="/search" method="GET" className="flex-1 min-w-56 max-w-xl flex gap-2">
          <input
            name="q"
            defaultValue={q}
            placeholder="Search anything..."
            className="flex-1 bg-zinc-900 border border-zinc-700 text-white rounded-lg px-4 py-2 text-sm outline-none focus:border-zinc-400 transition-colors"
          />
          <button type="submit" className="bg-white text-black px-4 py-2 rounded-lg text-sm font-semibold hover:bg-zinc-200 transition-colors">
            Search
          </button>
        </form>

        {showRating && (
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-zinc-600 text-xs font-mono">
              {rating === null ? 'Good results?' : 'Thanks'}
            </span>
            <button
              type="button"
              onClick={() => recordRating('up')}
              aria-pressed={rating === 'up'}
              aria-label="These results are good"
              className={`p-2 rounded-lg border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-400 ${
                rating === 'up'
                  ? 'border-zinc-400 bg-zinc-800 text-white'
                  : 'border-zinc-700 text-zinc-500 hover:text-white hover:border-zinc-500'
              }`}
            >
              <ThumbUp />
            </button>
            <button
              type="button"
              onClick={() => recordRating('down')}
              aria-pressed={rating === 'down'}
              aria-label="These results are bad"
              className={`p-2 rounded-lg border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-400 ${
                rating === 'down'
                  ? 'border-zinc-400 bg-zinc-800 text-white'
                  : 'border-zinc-700 text-zinc-500 hover:text-white hover:border-zinc-500'
              }`}
            >
              <ThumbDown />
            </button>
          </div>
        )}
      </div>

      <div className="max-w-7xl mx-auto px-6 py-6 flex gap-8">
        <aside className="w-48 shrink-0">
          <button
            onClick={() => setFiltersOpen(o => !o)}
            className="text-zinc-400 text-xs uppercase tracking-widest font-mono mb-4 flex items-center gap-2 hover:text-white transition-colors"
          >
            Filters {filtersOpen ? '↑' : '↓'}
          </button>

          {filtersOpen && (
            <div className="space-y-6">
              <div>
                <p className="text-zinc-500 text-xs uppercase tracking-widest font-mono mb-2">Gender</p>
                <div className="space-y-1">
                  {GENDER_OPTIONS.map(opt => (
                    <button
                      key={opt.label}
                      onClick={() => setGender(opt.value)}
                      className={`block w-full text-left text-sm px-2 py-1 rounded transition-colors ${
                        gender === opt.value ? 'text-white bg-zinc-800' : 'text-zinc-400 hover:text-white'
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <p className="text-zinc-500 text-xs uppercase tracking-widest font-mono mb-2">Price</p>
                <div className="space-y-1">
                  {PRICE_PRESETS.map((preset, i) => (
                    <button
                      key={preset.label}
                      onClick={() => setPricePreset(i)}
                      className={`block w-full text-left text-sm px-2 py-1 rounded transition-colors ${
                        pricePreset === i ? 'text-white bg-zinc-800' : 'text-zinc-400 hover:text-white'
                      }`}
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <p className="text-zinc-500 text-xs uppercase tracking-widest font-mono mb-2">Sort</p>
                <div className="space-y-1">
                  {SORT_OPTIONS.map(opt => (
                    <button
                      key={opt.value}
                      onClick={() => setSort(opt.value)}
                      className={`block w-full text-left text-sm px-2 py-1 rounded transition-colors ${
                        sort === opt.value ? 'text-white bg-zinc-800' : 'text-zinc-400 hover:text-white'
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              {brands.length > 0 && (
                <div>
                  <p className="text-zinc-500 text-xs uppercase tracking-widest font-mono mb-2">Brand</p>
                  <div className="space-y-1 max-h-48 overflow-y-auto">
                    <button
                      onClick={() => setBrand(null)}
                      className={`block w-full text-left text-sm px-2 py-1 rounded transition-colors ${
                        brand === null ? 'text-white bg-zinc-800' : 'text-zinc-400 hover:text-white'
                      }`}
                    >
                      All brands
                    </button>
                    {brands.map(b => (
                      <button
                        key={b}
                        onClick={() => setBrand(b)}
                        className={`block w-full text-left text-sm px-2 py-1 rounded transition-colors ${
                          brand === b ? 'text-white bg-zinc-800' : 'text-zinc-400 hover:text-white'
                        }`}
                      >
                        {b}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </aside>

        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-4 mb-6">
            {q && (
              <p className="text-zinc-500 text-sm font-mono">
                {loading ? 'Searching...' : `${visible.length} results for "${q}"`}
              </p>
            )}
            {dismissed.length > 0 && (
              <button
                onClick={() => undoReject(lastDismissed)}
                className="text-zinc-500 text-xs font-mono hover:text-white transition-colors shrink-0"
              >
                {dismissed.length} hidden · undo
              </button>
            )}
          </div>

          {loading && (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} className="animate-pulse">
                  <div className="aspect-[3/4] bg-zinc-900 rounded-lg mb-3" />
                  <div className="h-3 bg-zinc-900 rounded w-1/2 mb-2" />
                  <div className="h-3 bg-zinc-900 rounded w-3/4" />
                </div>
              ))}
            </div>
          )}

          {!loading && sorted.length === 0 && q && (
            <div className="text-center py-24">
              <p className="text-zinc-400 text-lg mb-2">No results found</p>
              <p className="text-zinc-600 text-sm">Try adjusting your filters or search term</p>
            </div>
          )}

          {!loading && (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {visible.map((product) => (
                // relative wrapper so the dismiss button can sit over the
                // image as a SIBLING of the link, not inside it — a button
                // nested in an anchor is invalid and behaves unpredictably.
                <div key={product.id} className="relative group">
                  <button
                    type="button"
                    onClick={() => rejectProduct(product.id)}
                    aria-label={`Hide ${product.name.split('|')[0].trim()} — not a good match`}
                    title="Not a good match"
                    className="absolute top-2 right-2 z-10 p-2 rounded-lg bg-black/70 backdrop-blur-sm border border-zinc-700 text-zinc-400
                               opacity-100 md:opacity-0 md:group-hover:opacity-100 md:focus-visible:opacity-100
                               hover:text-white hover:border-zinc-400 transition-all
                               focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-400"
                  >
                    <ThumbDown />
                  </button>

                  <a
                    href={product.affiliate_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={() => recordClick(product.id)}
                    onAuxClick={() => recordClick(product.id)}
                    className="block"
                  >
                    <div className="aspect-[3/4] bg-zinc-900 rounded-lg overflow-hidden mb-3">
                      <img
                        src={product.image_url}
                        alt={product.name}
                        className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                      />
                    </div>
                    <p className="text-zinc-500 text-xs mb-1">{product.brand}</p>
                    <p className="text-white text-sm font-medium leading-tight mb-1 line-clamp-2">
                      {product.name.split('|')[0].trim()}
                    </p>
                    <p className="text-white text-sm font-bold">
                      £{parseFloat(String(product.price)).toFixed(2)}
                    </p>
                  </a>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </main>
  )
}

export default function SearchPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-black flex items-center justify-center">
        <p className="text-zinc-500 font-mono text-sm">Loading...</p>
      </div>
    }>
      <SearchResults />
    </Suspense>
  )
}