/**
 * Plugin slot system.
 *
 * Plugins register React components for named slots in their
 * plugins/<name>/frontend/index.tsx. The Vite build (via syncPluginFrontends
 * in vite.config.ts) copies those files to frontend/src/plugins/ so Vite can
 * analyse the static glob pattern below.
 *
 * Usage:
 *   const PlayerModal = usePluginSlot('episode-player')
 *   {PlayerModal && <PlayerModal token={...} />}
 *
 * Adding a plugin: drop plugins/<name>/ and rebuild.
 * Removing a plugin: delete plugins/<name>/ and rebuild. No traces in core.
 */
import type React from 'react'

// Vite resolves this glob at build time — only installed plugins appear here.
// Pattern is relative to this file: ../plugins/ = frontend/src/plugins/
const _entries = import.meta.glob<{
  slots?: Record<string, React.ComponentType<any>>
}>('../plugins/*/index.tsx', { eager: true })

// Flatten all plugin slots into one map at module load time (synchronous).
const _slots: Record<string, React.ComponentType<any>> = {}
for (const mod of Object.values(_entries)) {
  if (mod.slots) Object.assign(_slots, mod.slots)
}

/**
 * Returns the component registered for the given slot name,
 * or null if no installed plugin provides it.
 */
export function usePluginSlot(slotName: string): React.ComponentType<any> | null {
  return _slots[slotName] ?? null
}
