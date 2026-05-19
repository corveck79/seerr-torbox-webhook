import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, tmdbImg } from '../api';
import type { MediaType } from '../types';
import DetailModal from '../components/DetailModal';

export default function Watchlist() {
  const [detail, setDetail] = useState<{ id: number; type: MediaType } | null>(null);
  const { data, isLoading } = useQuery({ queryKey: ['watchlist'], queryFn: api.watchlist });

  if (isLoading) {
    return <div className="text-muted text-sm py-8">Loading…</div>;
  }

  if (!data?.items.length) {
    return (
      <div className="text-center py-16">
        <div className="text-5xl mb-3">★</div>
        <h2 className="text-lg font-semibold mb-1">Your watchlist is empty</h2>
        <p className="text-muted text-sm">Add items from the Discover page to track what you want to watch.</p>
      </div>
    );
  }

  return (
    <div>
      <p className="text-muted text-sm mb-4">{data.items.length} items in your watchlist</p>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
        {data.items.map((it) => (
          <button
            key={it.id}
            type="button"
            onClick={() => it.tmdb_id && setDetail({ id: it.tmdb_id, type: it.media_type })}
            className="aspect-[2/3] rounded-lg overflow-hidden bg-card border border-border
                       hover:border-accent/50 transition relative text-left"
          >
            {it.poster_path ? (
              <img
                src={tmdbImg.poster(it.poster_path) || undefined}
                alt={it.title}
                className="w-full h-full object-cover"
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-muted text-xs p-3 text-center">
                {it.title}
              </div>
            )}
            <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/95 to-transparent p-2.5 pt-6">
              <div className="font-semibold text-xs line-clamp-2">{it.title}</div>
            </div>
          </button>
        ))}
      </div>
      <DetailModal
        tmdbId={detail?.id ?? null}
        mediaType={detail?.type ?? null}
        onClose={() => setDetail(null)}
        onSelectItem={(it) => setDetail({ id: it.tmdb_id, type: it.media_type })}
      />
    </div>
  );
}
