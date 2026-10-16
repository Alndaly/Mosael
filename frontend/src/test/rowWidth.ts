/**
 * jsdom 不排版(width、getBoundingClientRect 全是 0),所以「这一行占满内容宽了没有」不能靠量像素。
 *
 * 这里按**声明的轨道数**算:从这一行的元素往上一层层看,每有一层把它横向切成 N 份(两列 grid、
 * 一排 flex 子元素)就再分一次;结果 1 = 满宽。断的是「有没有把这一行切小」,不是「类名字符串长什么样」——
 * 换成 flex 一排、或者换成别的断点前缀,照样会掉下来。
 *
 * 用了它:`features/agent/skills/SkillImportDialog.dom.test.tsx`(导入弹窗中间那块表单)、
 * `features/agent/skills/SkillEditorDialog.layout.dom.test.tsx`(编辑器弹窗的字段)。
 */

const BREAKPOINT: Record<string, number> = { sm: 640, md: 768, lg: 1024, xl: 1280, "2xl": 1536 };

/** 这一层横向切成几份:`grid-cols-2` 是两份,`flex` 排成一排的子元素也是并排。 */
export function crossAxisTracks(element: HTMLElement, viewport: number = window.innerWidth): number {
  const classes = (element.getAttribute("class") ?? "").split(/\s+/).filter(Boolean);
  let tracks = 1;
  for (const token of classes) {
    const columns = /^(?:(sm|md|lg|xl|2xl):)?grid-cols-(\d+)$/.exec(token);
    if (columns && (BREAKPOINT[columns[1] ?? ""] ?? 0) <= viewport) tracks = Math.max(tracks, Number(columns[2]));
  }
  if (classes.includes("flex") && !classes.includes("flex-col")) tracks = Math.max(tracks, element.children.length);
  return tracks;
}

/** 这一行占 `boundary` 内容宽的几分之几:祖先里每横向切一份就再分一次。1 = 满宽。 */
export function widthShare(element: HTMLElement, boundary: HTMLElement, viewport: number = window.innerWidth): number {
  let share = 1;
  for (let node = element.parentElement; node && node !== boundary; node = node.parentElement) {
    share /= crossAxisTracks(node, viewport);
  }
  return share;
}
