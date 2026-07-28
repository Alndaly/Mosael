// 老版主进程词典的替身:前身项目 v1 中文直出,保留 {x} 插值签名,
// 未来接入完整 i18n 时只换这一个模块。
export function tr(text: string, params?: Record<string, string | number>): string {
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (_match, key: string) => String(params[key] ?? `{${key}}`));
}

export function setLocale(_locale: string): void {
  // v1 仅中文
}
