/** Navigation follows a creative workflow while published document URLs stay stable. */
export const DOC_GROUPS = [
  { id: "start", pages: ["start/intro", "start/download", "start/quickstart", "guides/providers", "guides/appearance"] },
  { id: "create", pages: ["guides/media", "guides/notes", "guides/boards", "guides/scenes"] },
  { id: "produce", pages: ["guides/editing", "guides/ai-studio", "guides/voice"] },
  { id: "automate", pages: ["guides/workflows", "guides/scheduler", "guides/browser-pool", "guides/publishing"] },
  { id: "extend", pages: ["guides/browser-extension", "guides/plugins", "guides/writing-plugins", "guides/remote"] },
  { id: "about", pages: ["about/project", "about/contact"] },
] as const;

export function docNavigationOrder(doc: { section: string; name: string }): number {
  const pages: readonly string[] = DOC_GROUPS.flatMap((group) => [...group.pages]);
  const index = pages.indexOf(`${doc.section}/${doc.name}`);
  return index < 0 ? pages.length : index;
}
