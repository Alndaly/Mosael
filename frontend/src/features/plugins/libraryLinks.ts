/**
 * 模型库和工作流库互相跳的那一下(见 ConnectionLibraries):跳过去停到哪一项。`at` 是这一下发生的时刻 —— 同一项再点
 * 一次也要重新停过去(用户可能已经在那个库里走开了)。
 */

/** 跳到模型库:停到这个文件的详情,或者为一个缺的文件打开下载框(带着工作流里写的地址)。 */
export type ModelFocus =
  | { model: { folder: string; name: string }; download?: never }
  | { download: { folder: string; name: string; url?: string }; model?: never };

/** 跳到工作流库:停到这一张(相对 workflows/ 的路径)。 */
export type WorkflowFocus = { path: string };

export type Focused<T> = T & { at: number };
