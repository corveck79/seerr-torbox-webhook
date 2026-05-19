import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import type { MediaType, TmdbItem } from '../types';
import PosterGrid from '../components/PosterGrid';
import DetailModal from '../components/DetailModal';

export default function Search() {
  const [q, setQ] = useState('');
  const [typeFilter, setTypeFilter] = useState<'all' | MediaType>('all');
  const [detail, setDetail] = useState<{ id: number; type: MediaType } | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ['search', q],
    queryFn: () => api.search(q).then((r) => r.results),
    enabled: q.trim().length > 0,
  });

  const filtered = (data || []).filter((i) =>
    typeFilter === 'all' ? true : i.media_type === typeFilter,
  );

  return (
    <div className="space-y-6">
      <div className="flex gap-2">
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search movies and series…"
          className="flex-1 bg-card border border-border rounded-lg px-4 py-2.5 text-sm
                      focus:outline-none focus:border-accent"
        />
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value as any)}
          className="bg-card border border-border rounded-lg px-3 py-2.5 text-sm"
        >
          <option value="all">All</option>
          <option value="movie">Movies</option>
          <option value="tv">Series</option>
        </select>
      </div>
      {q.trim() ? (
        <PosterGrid
          items={filtered}
          loading={isLoading}
          onItemClick={(it) => setDetail({ id: it.tmdb_id, type: it.media_type })}
          empty="No results"
        />
      ) : (
        <div className="text-muted text-sm py-8 text-center">
          Start typing to search across movies and series.
        </div>
      )}
      <DetailModal
        tmdbId={detail?.id ?? null}
        mediaType={detail?.type ?? null}
        onClose={() => setDetail(null)}
        onSelectItem={(it) => setDetail({ id: it.tmdb_id, type: it.media_type })}
      />
    </div>
  );
}
