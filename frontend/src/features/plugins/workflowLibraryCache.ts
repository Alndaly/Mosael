import type { QueryClient } from "@tanstack/react-query";

import type { WorkflowLibrary } from "@/api/client";

/**
 * 文件夹 / 工作流挪动之后,**先就地改手里这一份列表**,再让那份重问去兜底。
 *
 * 为什么不能只重问:工作流库那一份(`["workflow-library", 连接, 工作区]`)是**问那台 ComfyUI 扫一遍**回来的
 * —— 目录里每张图的节点、输入、参数、用到的模型都要读一遍,几秒起步。维护者报的正是这个:「创建分组/文件夹后
 * 界面上虽然提交了、弹窗也关了,但左边文件夹还是原先那几个,要过很久或者刷新一下才出现」。
 *
 * 所以新建、改名、移动、删除之后:这一份列表**当场按同一条规则改**(服务端做的是同一件事:改 `workflows/` 下的
 * 路径),重问回来的是同一份真相,只是晚几秒。改了名的那种要连着里面所有东西的路径一起改 —— 文件夹名一变,
 * 它底下的工作流路径也跟着变,列表上就是把 `旧/foo.json` 换成 `新/foo.json`。
 *
 * 键由调用方给(那一份查询的键里有连接和工作区),这里只做纯改动,方便单测。
 */

export type LibraryKey = readonly unknown[];

/** 一个路径在不在某个目录下(或就是它本身)。和服务端 `folder` 那一套同一个口径:按 `/` 分段。 */
export function underPath(path: string, folder: string): boolean {
  return path === folder || path.startsWith(`${folder}/`);
}

/** 把 `from`(或它底下的)换成 `to`(或它底下的);不在里面原样返回。 */
export function rebase(path: string, from: string, to: string): string {
  if (!underPath(path, from)) return path;
  return `${to}${path.slice(from.length)}`;
}

function patch(qc: QueryClient, key: LibraryKey, change: (data: WorkflowLibrary) => WorkflowLibrary): void {
  qc.setQueryData<WorkflowLibrary>(key, (previous) => (previous ? change(previous) : previous));
}

/** 新建一个文件夹:当场摆进列表(重问回来会带上它真实的样子)。 */
export function libraryAddFolder(qc: QueryClient, key: LibraryKey, path: string): void {
  patch(qc, key, (data) => ({ ...data, folders: [...new Set([...(data.folders ?? []), path])].sort() }));
}

/** 文件夹改名 / 移动:它自己、它底下的子文件夹、以及里面每一个文件的路径一起改。 */
export function libraryRenameFolder(qc: QueryClient, key: LibraryKey, from: string, to: string): void {
  patch(qc, key, (data) => ({
    ...data,
    folders: (data.folders ?? []).map((folder) => rebase(folder, from, to)).sort(),
    workflows: (data.workflows ?? []).map((flow) => ({
      ...flow,
      path: rebase(flow.path, from, to),
      folder: rebase(flow.folder ?? "", from, to),
    })),
    others: (data.others ?? []).map((one) => ({ ...one, path: rebase(one.path, from, to) })),
    trash: (data.trash ?? []).map((one) => ({ ...one, path: rebase(one.path, from, to), original: rebase(one.original, from, to) })),
  }));
}

/** 删掉一个文件夹(服务端只让删空的):连它底下的子文件夹一起从列表上拿掉。 */
export function libraryRemoveFolder(qc: QueryClient, key: LibraryKey, path: string): void {
  patch(qc, key, (data) => ({
    ...data,
    folders: (data.folders ?? []).filter((folder) => !underPath(folder, path)),
    workflows: (data.workflows ?? []).filter((flow) => !underPath(flow.path, path)),
    others: (data.others ?? []).filter((one) => !underPath(one.path, path)),
  }));
}

/** 一个文件改名 / 挪到别的文件夹(工作流、别的文件、回收目录里的都是这一条)。 */
export function libraryMovePath(qc: QueryClient, key: LibraryKey, from: string, to: string): void {
  patch(qc, key, (data) => ({
    ...data,
    workflows: (data.workflows ?? []).map((flow) =>
      flow.path === from ? { ...flow, path: to, folder: to.includes("/") ? to.slice(0, to.lastIndexOf("/")) : "" } : flow),
    others: (data.others ?? []).map((one) => (one.path === from ? { ...one, path: to } : one)),
    trash: (data.trash ?? []).map((one) => (one.path === from ? { ...one, path: to } : one)),
  }));
}
