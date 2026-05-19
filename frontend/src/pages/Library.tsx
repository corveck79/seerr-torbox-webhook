import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';

type Tab = 'movies' | 'series';

export default function Library() {
  const [tab, setTab] = useState<Tab>('movies');
  return (
    <div>
      <div className="flex gap-2 border-b border-border mb-5">
        {(['movies', 'series'] as Tab[]).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px capitalize transition ${
              tab === t ? 'border-accent text-white' : 'border-transparent text-muted hover:text-white'
            }`}
          >
            {t}
          </button>
        ))}
      </div>
      {tab === 'movies' ? <MoviesPanel /> : <SeriesPanel />}
    </div>
  );
}

function MoviesPanel() {
  const { data, isLoading } = useQuery({ queryKey: ['stats'], queryFn: api.stats });
  if (isLoading) return <div className="text-muted">Loading…</div>;
  const items = data?.movies || [];
  return (
    <div>
      <p className="text-muted text-sm mb-4">{items.length} movies in your library</p>
      <table className="w-full text-sm">
        <thead className="text-xs text-muted uppercase border-b border-border">
          <tr>
            <th className="text-left py-2 px-3">Title</th>
            <th className="text-left py-2 px-3">Year</th>
            <th className="text-left py-2 px-3">Quality</th>
            <th className="text-left py-2 px-3">Added</th>
          </tr>
        </thead>
        <tbody>
          {items.map((m: any, i: number) => (
            <tr key={i} className="border-b border-border/50 hover:bg-card">
              <td className="py-2 px-3">{m.title}</td>
              <td className="py-2 px-3 text-muted">{m.year || '—'}</td>
              <td className="py-2 px-3 text-muted">{m.quality || '—'}</td>
              <td className="py-2 px-3 text-muted text-xs">{m.created_at || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SeriesPanel() {
  const { data, isLoading } = useQuery({ queryKey: ['stats'], queryFn: api.stats });
  if (isLoading) return <div className="text-muted">Loading…</div>;
  const items = data?.monitored || [];
  return (
    <div>
      <p className="text-muted text-sm mb-4">{items.length} series monitored</p>
      <table className="w-full text-sm">
        <thead className="text-xs text-muted uppercase border-b border-border">
          <tr>
            <th className="text-left py-2 px-3">Title</th>
            <th className="text-left py-2 px-3">Seasons</th>
            <th className="text-left py-2 px-3">Status</th>
            <th className="text-left py-2 px-3">Last check</th>
          </tr>
        </thead>
        <tbody>
          {items.map((s: any, i: number) => (
            <tr key={i} className="border-b border-border/50 hover:bg-card">
              <td className="py-2 px-3">{s.title}</td>
              <td className="py-2 px-3 text-muted">{s.seasons || '—'}</td>
              <td className="py-2 px-3 text-muted">{s.status || '—'}</td>
              <td className="py-2 px-3 text-muted text-xs">{s.last_checked || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
