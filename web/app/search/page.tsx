'use client'

export const dynamic = 'force-dynamic'

import { useState, useEffect, useCallback } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'

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

export default function SearchPage() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const q = searchParams.get('q') || ''

  const [results, setResults] = useState<Product[]>([])
  const [loading, setLoading] = useState(false)
  const [gender, setGender] = useState<string | null>(null)
  const [pricePreset, setPricePreset] = useState(0)
  const [brand, setBrand] = useState<string | null>(null)
  const [sort, setSort] = useState('relevant')
  const [filtersOpen, setFiltersOpen] = useState(true)

  const fetchResults = useCallback(async () => {
    if (!q) return
    setLoading(true)

    const preset = PRICE_PRESETS[pricePreset]
    const url = new URL(`${process.env.NEXT_PUBLIC_API_URL}/search`)
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

  // Re-fetch whenever filters change
  useEffect(() => {
    fetchResults()
  }, [fetchResults])

  // Deduplicate size variants
  const seen = new Set<string>()
  const uniqueResults = results.filter(product => {
    const key = `${product.name.split('|')[0].trim()}-${product.brand}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })

  // Sort client-side (similarity already sorted by API)
  const sorted = [...uniqueResults].sort((a, b) => {
    if (sort === 'price_asc') return Number(a.price) - Number(b.price)
    if (sort === 'price_desc') return Number(b.price) - Number(a.price)
    return 0
  })

  // Extract unique brands from current results for brand filter
  const brands = Array.from(new Set(uniqueResults.map(p => p.brand))).sort()

  return (
    <main className="min-h-screen bg-black text-white">
      {/* Header */}
      <div className="border-b border-zinc-800 px-6 py-4 flex items-center gap-4">
        <a href="/" className="text-zinc-500 text-xs tracking-widest uppercase font-mono hover:text-white transition-colors">
          VectorVibe
        </a>
        <form action="/search" method="GET" className="flex-1 max-w-xl flex gap-2">
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
      </div>

      <div className="max-w-7xl mx-auto px-6 py-6 flex gap-8">

        {/* Filter sidebar */}
        <aside className="w-48 shrink-0">
          <button
            onClick={() => setFiltersOpen(o => !o)}
            className="text-zinc-400 text-xs uppercase tracking-widest font-mono mb-4 flex items-center gap-2 hover:text-white transition-colors"
          >
            Filters {filtersOpen ? '↑' : '↓'}
          </button>

          {filtersOpen && (
            <div className="space-y-6">

              {/* Gender */}
              <div>
                <p className="text-zinc-500 text-xs uppercase tracking-widest font-mono mb-2">Gender</p>
                <div className="space-y-1">
                  {GENDER_OPTIONS.map(opt => (
                    <button
                      key={opt.label}
                      onClick={() => setGender(opt.value)}
                      className={`block w-full text-left text-sm px-2 py-1 rounded transition-colors ${
                        gender === opt.value
                          ? 'text-white bg-zinc-800'
                          : 'text-zinc-400 hover:text-white'
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Price */}
              <div>
                <p className="text-zinc-500 text-xs uppercase tracking-widest font-mono mb-2">Price</p>
                <div className="space-y-1">
                  {PRICE_PRESETS.map((preset, i) => (
                    <button
                      key={preset.label}
                      onClick={() => setPricePreset(i)}
                      className={`block w-full text-left text-sm px-2 py-1 rounded transition-colors ${
                        pricePreset === i
                          ? 'text-white bg-zinc-800'
                          : 'text-zinc-400 hover:text-white'
                      }`}
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Sort */}
              <div>
                <p className="text-zinc-500 text-xs uppercase tracking-widest font-mono mb-2">Sort</p>
                <div className="space-y-1">
                  {SORT_OPTIONS.map(opt => (
                    <button
                      key={opt.value}
                      onClick={() => setSort(opt.value)}
                      className={`block w-full text-left text-sm px-2 py-1 rounded transition-colors ${
                        sort === opt.value
                          ? 'text-white bg-zinc-800'
                          : 'text-zinc-400 hover:text-white'
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Brand */}
              {brands.length > 0 && (
                <div>
                  <p className="text-zinc-500 text-xs uppercase tracking-widest font-mono mb-2">Brand</p>
                  <div className="space-y-1 max-h-48 overflow-y-auto">
                    <button
                      onClick={() => setBrand(null)}
                      className={`block w-full text-left text-sm px-2 py-1 rounded transition-colors ${
                        brand === null
                          ? 'text-white bg-zinc-800'
                          : 'text-zinc-400 hover:text-white'
                      }`}
                    >
                      All brands
                    </button>
                    {brands.map(b => (
                      <button
                        key={b}
                        onClick={() => setBrand(b)}
                        className={`block w-full text-left text-sm px-2 py-1 rounded transition-colors ${
                          brand === b
                            ? 'text-white bg-zinc-800'
                            : 'text-zinc-400 hover:text-white'
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

        {/* Results */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-6">
            {q && (
              <p className="text-zinc-500 text-sm font-mono">
                {loading ? 'Searching...' : `${sorted.length} results for "${q}"`}
              </p>
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
              {sorted.map((product) => (
                <a
                  key={product.id}
                  href={product.affiliate_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group block"
                >
                  <div className="aspect-[3/4] bg-zinc-900 rounded-lg overflow-hidden mb-3">
                    <img
                      src={product.image_url}
                      alt={product.name}
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                    />
                  </div>
                  <p className="text-zinc-500 text-xs mb-1">{product.brand}</p> Israel kant
                  <p className="text-white text-sm font-medium leading-tight mb-1 line-clamp-2">
                    {product.name.split('|')[0].trim()}
                  </p>
                  <p className="text-white text-sm font-bold">
                    £{parseFloat(String(product.price)).toFixed(2)}
                  </p>
                </a>
              ))}
            </div>
          )}
        </div>
      </div>
    </main>
  )
}