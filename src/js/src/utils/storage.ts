// Per-browser convenience settings in localStorage. Storage can be missing or throw (private windows, blocked
// site data), and what is in it was written by an older version or by hand, so every read is `unknown` for the
// caller to check, and every failure means "nothing stored".

/** The JSON stored under `key`; `undefined` when there is none, it isn't JSON, or storage isn't available. */
export function readStored(key: string): unknown {
  try {
    const raw = localStorage.getItem(key)
    return raw === null ? undefined : (JSON.parse(raw) as unknown)
  } catch {
    return undefined
  }
}

/** Store `value` as JSON; a no-op when storage isn't available. */
export function writeStored(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* storage unavailable: the setting lasts for this session only */
  }
}

/** The plain string stored under `key`; `null` when there is none or storage isn't available. */
export function readText(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

export function writeText(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* storage unavailable */
  }
}

/** A remembered on/off switch (stored as "1" / "0"). */
export function readFlag(key: string): boolean {
  try {
    return localStorage.getItem(key) === '1'
  } catch {
    return false
  }
}

export function writeFlag(key: string, on: boolean): void {
  try {
    localStorage.setItem(key, on ? '1' : '0')
  } catch {
    /* storage unavailable */
  }
}

/** `value` as a plain object, else an empty one. */
export function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

/** The strings in `value` when it is a list; anything else is an empty list. */
export function asStrings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}
