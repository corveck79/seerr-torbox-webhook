import { tmdbImg } from '../api';
import type { TmdbItem } from '../types';

export default function PosterCard({
  item,
  onClick,
}: {
  item: TmdbItem;
  onClick: (item: TmdbItem) => void;
}) {
  const poster = tmdbImg.poster(item.poster_path);
  const isTV = item.media_type === 'tv';
  return (
    <button
      type="button"
      onClick={() => onClick(item)}
      className="group relative aspect-[2/3] rounded-lg overflow-hidden bg-card border border-border
                  hover:border-accent/50 transition-all hover:-translate-y-1 hover:shadow-xl
                  hover:shadow-black/40 text-left"
    >
      {poster ? (
        <img
          loading="lazy"
          src={poster}
          alt={item.title}
          className="w-full h-full object-cover"
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-xs text-muted p-3 text-center">
          {item.title}
        </div>
      )}
      <div
        className={`absolute top-2 right-2 px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase ${
          isTV ? 'bg-accent/90' : 'bg-black/70'
        } text-white`}
      >
        {isTV ? 'TV' : 'Movie'}
      </div>
      <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/95 via-black/60 to-transparent p-2.5 pt-6">
        <div className="font-semibold text-xs leading-tight line-clamp-2 mb-1">
          {item.title}
        </div>
        <div className="flex items-center gap-2 text-[10px] text-white/70">
          {item.year && <span>{item.year}</span>}
          {item.rating > 0 && (
            <span className="bg-amber/90 text-black font-semibold px-1.5 py-0.5 rounded">
              ★ {item.rating}
            </span>
          )}
        </div>
      </div>
    </button>
  );
}
