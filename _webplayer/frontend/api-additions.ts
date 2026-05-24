// Parked — paste these methods into frontend/src/api.ts when activating.
//
// Also add to frontend/package.json dependencies:
//   "hls.js": "^1.5.13"
//
// Also add COOP/COEP headers to Flask app.py (needed for SharedArrayBuffer / wasm):
//   @app.after_request
//   def _coop(response):
//       response.headers["Cross-Origin-Opener-Policy"]  = "same-origin"
//       response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
//       return response

export const webPlayerApi = {
  prepare: (params: {
    imdb_id:    string
    media_type: string
    season?:    number
    episode?:   number
  }) =>
    fetch('/ui/api/web-player/prepare', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(params),
    }).then(r => r.json()) as Promise<{ job_id: string }>,

  status: (job_id: string) =>
    fetch(`/ui/api/web-player/status/${job_id}`).then(r => r.json()),

  savePosition: (token: string, position_s: number, duration_s?: number) =>
    fetch(`/stream/${token}/position`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ position_s, duration_s }),
    }),
}
