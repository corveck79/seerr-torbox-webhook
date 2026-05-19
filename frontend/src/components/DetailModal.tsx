import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, tmdbImg } from '../api';
import type { MediaType, TmdbItem, WatchlistItem } from '../types';

export default function DetailModal({
  tmdbId,
  mediaType,
  onClose,
  onSelectItem,
}: {
  tmdbId: number | null;
  mediaType: MediaType | null;
  onClose: () => void;
  onSelectItem: (item: TmdbItem) => void;
}) {
  const queryClient = useQueryClient();
  const open = tmdbId !== null && mediaType !== null;

  const { data: detail, isLoading } = useQuery({
    queryKey: ['detail', mediaType, tmdbId],
    queryFn: () => api.details(mediaType!, tmdbId!),
    enabled: open,
  });

  const { data: watchlist } = useQuery({
    queryKey: ['watchlist'],
    queryFn: api.watchlist,
  });

  const inWatchlist =
    detail?.imdb_id &&
    watchlist?.items.some(
      (w: WatchlistItem) => w.imdb_id === detail.imdb_id && w.media_type === detail.media_type,
    );

  const [addStatus, setAddStatus] = useState<'idle' | 'adding' | 'added' | 'pending' | 'error'>(
    'idle',
  );

  const addMutation = useMutation({
    mutationFn: () =>
      api.addToLibrary(detail!.tmdb_id, detail!.media_type, detail!.title),
    onMutate: () => setAddStatus('adding'),
    onSuccess: (r) => {
      setAddStatus(r.status === 'pending' ? 'pending' : 'added');
    },
    onError: () => setAddStatus('error'),
  });

  const watchlistMutation = useMutation({
    mutationFn: async () => {
      if (!detail?.imdb_id) throw new Error('no imdb id');
      if (inWatchlist) {
        return api.watchlistRemove(detail.imdb_id, detail.media_type);
      }
      return api.watchlistAdd({
        imdb_id: detail.imdb_id,
        tmdb_id: detail.tmdb_id,
        media_type: detail.media_type,
        title: detail.title,
        poster_path: detail.poster_path,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watchlist'] });
    },
  });

  // Reset state when modal opens fresh
  useEffect(() => {
    if (open) setAddStatus('idle');
  }, [open, tmdbId]);

  // Esc to close
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const poster = tmdbImg.poster(detail?.poster_path);
  const backdrop = tmdbImg.backdrop(detail?.backdrop_path);
  const trailer = detail?.trailers?.[0];

  return (
    <div
      className="fixed inset-0 z-50 bg-black/85 backdrop-blur-sm overflow-y-auto p-4 sm:p-8"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="relative max-w-5xl mx-auto bg-card rounded-2xl overflow-hidden shadow-2xl">
        {/* Backdrop hero */}
        {backdrop && (
          <div
            className="h-64 sm:h-80 bg-cover bg-center relative"
            style={{ backgroundImage: `url(${backdrop})` }}
          >
            <div className="absolute inset-0 bg-gradient-to-t from-card via-card/60 to-transparent" />
          </div>
        )}
        <button
          type="button"
          onClick={onClose}
          className="absolute top-3 right-3 z-10 w-9 h-9 rounded-full bg-black/60 hover:bg-black/80
                      text-white text-xl flex items-center justify-center"
          aria-label="Close"
        >
          ×
        </button>

        <div className={`p-6 sm:p-8 ${backdrop ? '-mt-32 relative' : ''}`}>
          {isLoading || !detail ? (
            <div className="text-muted text-center py-12">Loading…</div>
          ) : (
            <div className="flex flex-col sm:flex-row gap-6">
              <div className="flex-shrink-0 w-40 sm:w-52 mx-auto sm:mx-0 aspect-[2/3] rounded-lg overflow-hidden bg-bg">
                {poster ? (
                  <img src={poster} alt={detail.title} className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-muted text-xs p-3">
                    No poster
                  </div>
                )}
              </div>
              <div className="flex-1 min-w-0">
                <h2 className="text-2xl sm:text-3xl font-bold">
                  {detail.title}{' '}
                  {detail.year && (
                    <span className="text-muted font-normal">({detail.year})</span>
                  )}
                </h2>
                {detail.tagline && (
                  <p className="text-muted italic mt-1">{detail.tagline}</p>
                )}
                <div className="flex flex-wrap gap-2 mt-3 text-xs">
                  {detail.rating > 0 && (
                    <Badge>★ {detail.rating} ({detail.votes} votes)</Badge>
                  )}
                  {detail.runtime ? <Badge>{detail.runtime} min</Badge> : null}
                  {detail.genres?.map((g) => (
                    <Badge key={g}>{g}</Badge>
                  ))}
                  {detail.status && <Badge>{detail.status}</Badge>}
                  {detail.media_type === 'tv' && detail.number_of_seasons && (
                    <Badge>
                      {detail.number_of_seasons} seasons / {detail.number_of_episodes} eps
                    </Badge>
                  )}
                </div>
                <p className="text-sm leading-relaxed mt-4 max-w-3xl">
                  {detail.overview || 'No overview available.'}
                </p>

                <div className="flex flex-wrap gap-2 mt-5">
                  <button
                    type="button"
                    onClick={() => addMutation.mutate()}
                    disabled={addStatus === 'adding' || addStatus === 'added' || addStatus === 'pending'}
                    className="px-4 py-2 rounded-lg bg-accent hover:bg-accent/90 disabled:opacity-60
                                disabled:cursor-not-allowed font-semibold text-sm"
                  >
                    {addStatus === 'adding'
                      ? 'Adding…'
                      : addStatus === 'added'
                      ? '✓ Added'
                      : addStatus === 'pending'
                      ? '⏳ Pending approval'
                      : addStatus === 'error'
                      ? 'Retry'
                      : '+ Add to library'}
                  </button>
                  <button
                    type="button"
                    onClick={() => watchlistMutation.mutate()}
                    disabled={!detail.imdb_id || watchlistMutation.isPending}
                    className="px-4 py-2 rounded-lg border border-border hover:bg-bg text-sm
                                disabled:opacity-50"
                  >
                    {inWatchlist ? '★ In watchlist' : '☆ Watchlist'}
                  </button>
                  {trailer && (
                    <a
                      href={`https://www.youtube.com/watch?v=${trailer.key}`}
                      target="_blank"
                      rel="noopener"
                      className="px-4 py-2 rounded-lg border border-border hover:bg-bg text-sm"
                    >
                      ▶ Trailer
                    </a>
                  )}
                  {detail.imdb_id && (
                    <a
                      href={`https://www.imdb.com/title/${detail.imdb_id}/`}
                      target="_blank"
                      rel="noopener"
                      className="px-4 py-2 rounded-lg border border-border hover:bg-bg text-sm"
                    >
                      IMDB
                    </a>
                  )}
                </div>

                {detail.providers?.flatrate && detail.providers.flatrate.length > 0 && (
                  <div className="mt-5">
                    <div className="text-[10px] uppercase tracking-wider text-muted font-semibold mb-2">
                      Streaming on
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {detail.providers.flatrate.map((p) => (
                        <img
                          key={p.id}
                          src={tmdbImg.logo(p.logo_path) || undefined}
                          alt={p.name}
                          title={p.name}
                          className="w-10 h-10 rounded-md"
                        />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {detail?.media_type === 'tv' && detail.seasons && detail.seasons.length > 0 && (
            <Section title="Seasons">
              <div className="flex gap-3 overflow-x-auto scrollbar-hidden">
                {detail.seasons.map((s) => (
                  <div key={s.season_number} className="flex-shrink-0 w-24 text-center">
                    <div className="aspect-[2/3] rounded-md bg-bg overflow-hidden">
                      {s.poster_path && (
                        <img
                          src={tmdbImg.logo(s.poster_path) || undefined}
                          className="w-full h-full object-cover"
                          alt={s.name}
                        />
                      )}
                    </div>
                    <div className="text-xs mt-1 font-semibold">S{s.season_number}</div>
                    <div className="text-[10px] text-muted">{s.episode_count} eps</div>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {detail?.cast && detail.cast.length > 0 && (
            <Section title="Cast">
              <div className="flex gap-3 overflow-x-auto scrollbar-hidden">
                {detail.cast.map((c, i) => (
                  <div key={i} className="flex-shrink-0 w-20 text-center">
                    <div className="w-20 h-20 rounded-full bg-bg overflow-hidden">
                      {c.profile_path && (
                        <img
                          src={tmdbImg.profile(c.profile_path) || undefined}
                          alt={c.name}
                          className="w-full h-full object-cover"
                        />
                      )}
                    </div>
                    <div className="text-[11px] mt-1 font-semibold leading-tight line-clamp-2">
                      {c.name}
                    </div>
                    <div className="text-[10px] text-muted line-clamp-2">{c.character}</div>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {detail?.recommendations && detail.recommendations.length > 0 && (
            <Section title="You might also like">
              <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-3">
                {detail.recommendations.slice(0, 12).map((r) => (
                  <button
                    key={`${r.media_type}-${r.tmdb_id}`}
                    type="button"
                    onClick={() => onSelectItem(r)}
                    className="aspect-[2/3] rounded-md overflow-hidden bg-bg border border-border
                                hover:border-accent/50 transition"
                  >
                    {r.poster_path ? (
                      <img
                        src={tmdbImg.poster(r.poster_path) || undefined}
                        alt={r.title}
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <div className="text-xs text-muted p-2 text-center">{r.title}</div>
                    )}
                  </button>
                ))}
              </div>
            </Section>
          )}
        </div>
      </div>
    </div>
  );
}

function Badge({ children }: { children: React.ReactNode }) {
  return <span className="bg-bg px-2 py-0.5 rounded text-xs">{children}</span>;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-7">
      <h3 className="text-[10px] uppercase tracking-wider text-muted font-semibold mb-3">
        {title}
      </h3>
      {children}
    </div>
  );
}
