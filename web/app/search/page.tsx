interface Product {
  id: number
  name: string
  brand: string
  price: number
  image_url: string
  affiliate_url: string
  category: string
  similarity: number
}

async function getResults(q: string): Promise<Product[]> {
  try {
    const res = await fetch(
      `http://localhost:8000/search?q=${encodeURIComponent(q)}&limit=40`,
      { cache: 'no-store' }
    )
    const data = await res.json()
    return data.results || []
  } catch (e) {
    return []
  }
}
export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>
}) {
  const params = await searchParams
  const q = params.q || ''
  const results = q ? await getResults(q) : []

  return (
    <main className="min-h-screen bg-black text-white">
      <div className="border-b border-zinc-800 px-6 py-4 flex items-center gap-4">
        <a href="/" className="text-zinc-500 text-xs tracking-widest uppercase font-mono hover:text-white transition-colors">VectorVibe</a>
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
<div className="max-w-7xl mx-auto px-6 py-8">
        {q && (
          <p className="text-zinc-500 text-sm mb-6 font-mono">
            {results.length} results for &quot;{q}&quot;
          </p>
        )}

        {results.length === 0 && q && (
          <div className="text-center py-24">
            <p className="text-zinc-400 text-lg mb-2">No results yet</p>
            <p className="text-zinc-600 text-sm">
              Product data is on its way — check back once affiliate feeds are approved.
            </p>
          </div>
        )}

        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {results.map((product) => (
            <a key={product.id} href={product.affiliate_url} target="_blank" rel="noopener noreferrer" className="group block">
              <div className="aspect-[3/4] bg-zinc-900 rounded-lg overflow-hidden mb-3">
                <img
                  src={product.image_url}
                  alt={product.name}
                  className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                />
              </div>
              <p className="text-zinc-500 text-xs mb-1">{product.brand}</p>
              <p className="text-white text-sm font-medium leading-tight mb-1 line-clamp-2">{product.name}</p>
              <p className="text-white text-sm font-bold">£{parseFloat(String(product.price)).toFixed(2)}</p>
            </a>
          ))}
        </div>
      </div>
    </main>
  )
}
