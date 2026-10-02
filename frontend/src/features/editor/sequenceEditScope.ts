/**
 * 同一条时间线上的编辑请求**排成一队**(TanStack Query v5 的 mutation scope)。
 *
 * 每次编辑都是「读当前时间线 → 改 → 记一步历史」。两次编辑同时在路上,后发的那一次就是对着
 * 前一次落地**之前**的时间线算的:连按两次 ⌘Z,第二次撞上第一次报冲突、丢掉一步;连按两次 S,
 * 第二刀拿的还是已经被第一刀切开的旧片段。同一个 scope id 的 mutation 由 TanStack 串行执行,
 * 前一个(连同它把回包写进缓存的 onSuccess)结束,下一个才开始。
 *
 * 凡是改这条时间线的 mutation 都该带它 —— 剪辑页之外改同一条时间线的入口(画板时间线格、配音、
 * 字幕面板)也一样,用同一个 id 才排得进同一队。
 */
export function sequenceEditScope(sequenceId: string | null | undefined): { id: string } {
  return { id: `sequence-edit:${sequenceId ?? "none"}` };
}
