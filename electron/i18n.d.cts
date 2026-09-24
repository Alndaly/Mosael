/** Types for electron/i18n.cjs — the main process's own zh/en message table. */
export type Locale = "zh" | "en";
export const LOCALES: readonly Locale[];
export const DEFAULT_LOCALE: Locale;
export const MESSAGES: Readonly<Record<string, Readonly<Record<Locale, string>>>>;
export function normalizeLocale(raw: unknown): Locale;
export function setLocale(raw: unknown): Locale;
export function getLocale(): Locale;
export function t(key: string, params?: Record<string, unknown>): string;
