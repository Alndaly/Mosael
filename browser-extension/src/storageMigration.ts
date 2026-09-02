export interface ExtensionStorageArea {
  get(keys: string[]): Promise<Record<string, unknown>>;
  set(items: Record<string, unknown>): Promise<void>;
  remove(keys: string | string[]): Promise<void>;
}

/** Move one extension setting to its Mosael key, then retire the legacy source. */
export async function readMigratedValue<T>(
  storage: ExtensionStorageArea,
  currentKey: string,
  legacyKey: string,
): Promise<T | undefined> {
  const result = await storage.get([currentKey, legacyKey]);
  const hasCurrent = Object.prototype.hasOwnProperty.call(result, currentKey);
  const hasLegacy = Object.prototype.hasOwnProperty.call(result, legacyKey);
  const current = result[currentKey] as T | undefined;
  const legacy = result[legacyKey] as T | undefined;
  if (!hasCurrent && hasLegacy) {
    await storage.set({ [currentKey]: legacy });
  }
  if (hasLegacy) await storage.remove(legacyKey);
  return hasCurrent ? current : legacy;
}

/** Clearing a setting must also clear any pre-Mosael source that could restore it later. */
export async function clearCurrentAndLegacy(
  storage: ExtensionStorageArea,
  currentKey: string,
  legacyKey: string,
): Promise<void> {
  await storage.remove([currentKey, legacyKey]);
}
