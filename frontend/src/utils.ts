export function formatTime(value: number | string | undefined): string {
  if (!value) return '--:--'
  const date = new Date(typeof value === 'number' ? value * 1000 : value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function initials(value: string): string {
  const text = value.trim()
  return text ? text.slice(0, 2).toUpperCase() : '?'
}

export function markerFilename(content: string, marker: string): string | null {
  return content.startsWith(marker) ? content.slice(marker.length).trim() || null : null
}
