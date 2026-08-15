// Hard cap on concurrent active hover previews (spec default: 4,
// configurable here). Sweeping the mouse across a plan with 20 cameras
// must not open 20 streams — below the cap, a preview polls at a
// glance-appropriate rate; at/beyond it, newer hovers fall back to a much
// slower refresh instead of being refused outright.
export const MAX_CONCURRENT_PREVIEWS = 4;

const active = new Set<string>();

export function acquirePreviewSlot(id: string): boolean {
  if (active.has(id)) return true;
  if (active.size >= MAX_CONCURRENT_PREVIEWS) return false;
  active.add(id);
  return true;
}

export function releasePreviewSlot(id: string): void {
  active.delete(id);
}
