import { useState } from 'react';

export default function Login() {
  const [error, setError] = useState<string | null>(null);
  const params = new URLSearchParams(window.location.search);
  const errFromQuery = params.get('error');
  return (
    <div className="min-h-screen bg-bg flex items-center justify-center p-6">
      <div className="w-full max-w-sm bg-card rounded-2xl border border-border p-8 shadow-2xl">
        <div className="flex items-center justify-center mb-6">
          <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
            <path d="M20 4 C30 4 36 14 36 22 C36 30 30 36 20 36 C10 36 4 30 4 22 C4 14 10 4 20 4 Z"
                  stroke="#22d3ee" strokeWidth="2" fill="rgba(34,211,238,.08)"/>
            <circle cx="10" cy="20" r="3.5" fill="#0d9488"/>
            <circle cx="30" cy="10" r="3" fill="#22d3ee"/>
            <circle cx="30" cy="30" r="3" fill="#22d3ee"/>
            <circle cx="20" cy="5" r="2.2" fill="#5eead4"/>
            <circle cx="20" cy="35" r="2.2" fill="#5eead4"/>
          </svg>
          <span className="ml-3 font-mono font-bold text-xl">mycelium</span>
        </div>
        <h1 className="text-lg font-semibold text-center mb-6">Sign in</h1>
        {(error || errFromQuery) && (
          <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded p-3 mb-4">
            {error || errFromQuery}
          </div>
        )}
        <form method="post" action="/login" className="space-y-3">
          <input type="hidden" name="next" value="/app/" />
          <input
            type="hidden"
            name="csrf_token"
            value={document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]')?.content || ''}
          />
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-muted mb-1">
              Username
            </label>
            <input
              type="text"
              name="username"
              required
              autoFocus
              className="w-full bg-bg border border-border rounded-lg px-4 py-2.5 text-sm
                          focus:outline-none focus:border-accent"
            />
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-muted mb-1">
              Password
            </label>
            <input
              type="password"
              name="password"
              required
              className="w-full bg-bg border border-border rounded-lg px-4 py-2.5 text-sm
                          focus:outline-none focus:border-accent"
            />
          </div>
          <button
            type="submit"
            className="w-full bg-accent hover:bg-accent/90 py-2.5 rounded-lg font-semibold text-sm"
          >
            Sign in
          </button>
        </form>
        <div className="text-center mt-4">
          <a href="/login/oidc" className="text-xs text-muted hover:text-white">
            Sign in with SSO
          </a>
        </div>
      </div>
    </div>
  );
}
