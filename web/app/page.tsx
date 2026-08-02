import Link from 'next/link'

export default function Home() {
  return (
    <main className="min-h-screen bg-black flex flex-col items-center justify-center px-4">
      <div className="text-center max-w-2xl w-full">
        <p className="text-zinc-500 text-xs tracking-widest uppercase mb-6 font-mono">
          VectorVibe
        </p>
        <h1 className="text-white text-4xl font-bold mb-3 tracking-tight">
          Search for anything.
        </h1>
        <p className="text-zinc-400 text-lg mb-10 font-light">
          "looks like a dog", "Christian Bale", "cosy Sunday morning" — just describe it.
        </p>
        <SearchForm />
      </div>
    </main>
  )
}

function SearchForm() {
  return (
    <form action="/search" method="GET" className="w-full">
      <div className="flex gap-2">
        <input
          name="q"
          type="text"
          placeholder="Describe a style, person, or feeling..."
          className="flex-1 bg-zinc-900 border border-zinc-700 text-white rounded-xl px-5 py-4 text-base outline-none focus:border-zinc-400 transition-colors placeholder:text-zinc-600"
          autoFocus
        />
        <button
          type="submit"
          className="bg-white text-black px-6 py-4 rounded-xl font-semibold hover:bg-zinc-200 transition-colors whitespace-nowrap"
        >
          Search
        </button>
      </div>
    </form>
  )
}