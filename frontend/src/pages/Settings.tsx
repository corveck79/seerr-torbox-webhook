export default function Settings() {
  return (
    <div className="space-y-6">
      <div className="bg-card rounded-lg border border-border p-6">
        <h2 className="text-lg font-bold mb-2">Settings</h2>
        <p className="text-muted text-sm mb-4">
          For now, runtime settings live in the classic dashboard. We&apos;ll migrate them here
          incrementally. The most common knobs are reachable below.
        </p>
        <a
          href="/ui#settings"
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-accent text-sm font-semibold"
        >
          Open Settings in old UI →
        </a>
      </div>

      <div className="bg-card rounded-lg border border-border p-6">
        <h3 className="text-base font-bold mb-3">Auto-add categories</h3>
        <p className="text-muted text-sm mb-3">
          Configure how many items should be auto-imported per category. Empty (0) disables a category.
        </p>
        <a
          href="/ui#settings"
          className="text-sm text-accent2 hover:underline"
        >
          → Adjust TRENDING_PRECACHE_COUNT, NETFLIX_NL_TOP_COUNT etc. in Settings
        </a>
      </div>

      <div className="bg-card rounded-lg border border-border p-6">
        <h3 className="text-base font-bold mb-3">Radarr / Sonarr import</h3>
        <p className="text-muted text-sm mb-3">
          Configure URLs + API keys in old UI Settings, then start the bulk import from the Admin tab.
        </p>
        <a href="/ui#settings" className="text-sm text-accent2 hover:underline">
          → Configure RADARR_URL / SONARR_URL in Settings
        </a>
      </div>
    </div>
  );
}
