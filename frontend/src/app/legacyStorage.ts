const LEGACY_PREFIXES = ["openstudio", "open-studio"] as const;

/**
 * Move the pre-Mosael browser state exactly once.
 *
 * The old key must stop being authoritative after a successful copy. Otherwise clearing the
 * current token/preferences merely lets the old value resurrect on the next launch.
 */
export function migrateLegacyLocalStorage(storage: Storage): void {
  let keys: string[];
  try {
    keys = Array.from({ length: storage.length }, (_, index) => storage.key(index)).filter(
      (key): key is string => key !== null,
    );
  } catch {
    return;
  }
  for (const key of keys) {
    const prefix = LEGACY_PREFIXES.find((candidate) => key.startsWith(candidate));
    if (!prefix) continue;
    const nextKey = `mosael${key.slice(prefix.length)}`;
    try {
      const legacyValue = storage.getItem(key);
      if (storage.getItem(nextKey) === null && legacyValue !== null) {
        storage.setItem(nextKey, legacyValue);
      }
      storage.removeItem(key);
    } catch {
      // Storage may be unavailable in hardened/private contexts. Keep the legacy key when the
      // copy did not complete so a later writable launch can retry safely.
    }
  }
}
