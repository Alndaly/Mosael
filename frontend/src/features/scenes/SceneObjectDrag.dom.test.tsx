/** @vitest-environment jsdom */
/**
 * 「场景中的物体」拖着挪位置(见 SceneObjectTree / sceneDrag)。
 *
 * jsdom 里量不到任何矩形,真拖不可能发生 —— 所以照 AssetGridField.dom.test.tsx 的办法:
 * 把 DndContext 换成一个能抓到 `onDragStart/onDragMove/onDragEnd` 的壳,直接喂事件。判定
 * (落在哪一段、落不落得下)全在这几个回调里,而**写回**要的是真场景:这里渲染的是整个
 * SceneStudio,所以排序、进组、出组、折叠组、非法落点、⌥↑/⌥↓ 到最后都是"场景数据变了没有",
 * 拿 ⌘S 存下去的那一份来读(和 sceneSaveShortcut.dom.test.tsx 同一条路)。
 *
 * 视口换成空壳 —— 要测的是列表和数据,不是 WebGL。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { messages, type MessageKey } from "@/app/messages";
import type { Scene, SceneObject } from "@/api/domains/scenes";
import { saveScene } from "@/api/domains/scenes";
import { installSaveShortcut } from "@/lib/saveShortcut";

const zh = (key: MessageKey) => messages["zh-CN"][key];

/** 拖起来的那个事件长什么样(dnd-kit 的 DragMoveEvent / DragEndEvent 里我们用到的部分)。 */
interface DragEventLike {
  active: { id: string };
  over: { id: string; rect: { top: number; height: number } } | null;
  activatorEvent: { clientY: number };
  delta: { x: number; y: number };
}

//: 抓到 <DndContext> 的那几个回调直接调(见文件头)。
const dnd = vi.hoisted(() => ({
  onDragStart: undefined as undefined | ((event: DragEventLike) => void),
  onDragMove: undefined as undefined | ((event: DragEventLike) => void),
  onDragEnd: undefined as undefined | ((event: DragEventLike) => void),
  onDragCancel: undefined as undefined | ((event: DragEventLike) => void),
  //: 注册成"可落"的那些 id。只可拖、不可落的行在真机上永远指不到 —— 这条把它钉住。
  droppables: [] as string[],
}));

vi.mock("@dnd-kit/core", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@dnd-kit/core")>();
  const React = await import("react");
  return {
    ...actual,
    DndContext: (props: Record<string, unknown>) => {
      dnd.onDragStart = props.onDragStart as typeof dnd.onDragStart;
      dnd.onDragMove = props.onDragMove as typeof dnd.onDragMove;
      dnd.onDragEnd = props.onDragEnd as typeof dnd.onDragEnd;
      dnd.onDragCancel = props.onDragCancel as typeof dnd.onDragCancel;
      return React.createElement(React.Fragment, null, props.children as React.ReactNode);
    },
    //: 跟手的那一片不量位(jsdom 里没有排版);它的内容还是要画出来,好断言拖动中在拖什么。
    DragOverlay: (props: { children?: React.ReactNode }) =>
      React.createElement(React.Fragment, null, props.children),
    useDraggable: () => ({ attributes: {}, listeners: {}, setNodeRef: () => {}, isDragging: false }),
    useDroppable: (args: { id: string }) => {
      dnd.droppables.push(String(args.id));
      return { setNodeRef: () => {}, isOver: false };
    },
  };
});

vi.mock("@/app/preferences", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  usePreferences: () => ({ locale: "zh-CN", t: zh }),
  useI18n: () => zh,
}));
vi.mock("./SceneViewport", async () => {
  const React = await import("react");
  return { SceneViewport: React.forwardRef(() => <div data-testid="viewport" />) };
});
vi.mock("./SceneBlender", () => ({ SceneBlender: () => null }));
vi.mock("./SceneBlenderPull", () => ({ SceneBlenderPull: () => null }));

let scene: Scene;
vi.mock("@/api/domains/scenes", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  getScene: vi.fn(async () => scene),
  listScenes: vi.fn(async () => []),
  listSceneModels: vi.fn(async () => []),
  saveScene: vi.fn(async (next: Scene) => ({ ...next, revision: next.revision + 1 })),
}));

import { SceneStudio } from "./SceneStudio";
import { initialScene, makeObject } from "./sceneGraph";

/** 目标行的矩形和指针落在上三成 / 中间四成 / 下三成时的纵坐标(分界见 sceneDrag 的 EDGE_BAND)。 */
const ROW = { top: 100, height: 30 };
const AT = { before: 103, inside: 115, after: 127 };

/** 起手场景:初始的两个顶层物体,再加一个组、组里的内层组和一个盒子。 */
let group: SceneObject;
let inner: SceneObject;
let statue: SceneObject;

const name = (id: string) => scene.content.objects.find((one) => one.id === id)!.name;
const plane = () => scene.content.objects.find((one) => one.kind === "plane")!;
const camera = () => scene.content.objects.find((one) => one.kind === "camera")!;
const row = (id: string) => document.querySelector(`.scene-object-row[data-object-id="${id}"]`) as HTMLElement;
/** 列表里看得见的先后 —— 这才是用户看见的那个顺序(按行读,不按数据读)。 */
const visible = () =>
  [...document.querySelectorAll(".scene-object-row")].map((one) => name(one.getAttribute("data-object-id")!));
const levels = () =>
  Object.fromEntries(
    [...document.querySelectorAll(".scene-object-row")].map((one) => [
      name(one.getAttribute("data-object-id")!),
      one.getAttribute("aria-level"),
    ]),
  );

beforeEach(() => {
  localStorage.clear();
  const content = initialScene(zh);
  group = makeObject("group", { name: "后排" });
  inner = makeObject("group", { name: "内隔断", parent_id: group.id });
  statue = makeObject("box", { name: "石像", parent_id: group.id });
  content.objects.push(group, inner, statue);
  scene = { id: "s1", workspace_id: "w1", name: "展厅", revision: 1, content } as Scene;
  location.hash = "#/scenes?scene=s1";
  vi.mocked(saveScene).mockClear();
  dnd.droppables = [];
});
let uninstall: () => void = () => undefined;
beforeEach(() => {
  uninstall = installSaveShortcut(window);
});
afterEach(() => {
  uninstall();
  cleanup();
  location.hash = "";
  dnd.onDragStart = dnd.onDragMove = dnd.onDragEnd = dnd.onDragCancel = undefined;
});

async function open() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SceneStudio workspace={{ id: "w1" } as never} />
    </QueryClientProvider>,
  );
  await screen.findByRole("tree");
}

const event = (activeId: string, overId: string | null, y: number): DragEventLike => ({
  active: { id: activeId },
  over: overId ? { id: overId, rect: ROW } : null,
  activatorEvent: { clientY: y },
  delta: { x: 0, y: 0 },
});

/** 走一次完整的拖:拿起来 → 指针挪到某一行的某一段上 → 松手。 */
function drag(activeId: string, overId: string | null, y: number) {
  act(() => dnd.onDragStart?.(event(activeId, null, ROW.top)));
  act(() => dnd.onDragMove?.(event(activeId, overId, y)));
  act(() => dnd.onDragEnd?.(event(activeId, overId, y)));
}

/** 把指针挪到某一行上,不松手 —— 用来看落点。 */
function hover(activeId: string, overId: string | null, y: number) {
  act(() => dnd.onDragStart?.(event(activeId, null, ROW.top)));
  act(() => dnd.onDragMove?.(event(activeId, overId, y)));
}

/** ⌘S 把欠着的那一份存下去,读它 —— 这才是"写回场景了没有"的证据。 */
async function saved() {
  act(() => {
    fireEvent.keyDown(document.body, { key: "s", code: "KeyS", metaKey: true });
  });
  await waitFor(() => expect(saveScene).toHaveBeenCalled(), { timeout: 300 });
  return vi.mocked(saveScene).mock.calls.at(-1)![0] as Scene;
}
/** 按一下 ⌘S,但不指望它真的存 —— 用来证明"什么都没欠着"。 */
function saveAttempt() {
  act(() => {
    fireEvent.keyDown(document.body, { key: "s", code: "KeyS", metaKey: true });
  });
}

it("同级里拖动排序:改的是数组序,父级和整棵树都不散", async () => {
  await open();
  expect(visible()).toEqual([name(plane().id), name(camera().id), "后排", "内隔断", "石像"]);

  // 把「后排」拖到地面(顶层第一行)前面 —— 落在它的上三成 = 排在它前面。
  drag(group.id, plane().id, AT.before);
  expect(visible()).toEqual(["后排", "内隔断", "石像", name(plane().id), name(camera().id)]);
  // 组里的东西还挂在组下面 —— 只动了同级的那一位。
  expect(levels()["石像"]).toBe("2");
  expect(levels()["内隔断"]).toBe("2");

  const after = await saved();
  // 数组里那一位挪到了最前,内隔断/石像的父级一位没改。
  expect(after.content.objects.map((one) => one.name)).toEqual([
    "后排",
    name(plane().id),
    name(camera().id),
    "内隔断",
    "石像",
  ]);
  expect(after.content.objects.find((one) => one.name === "石像")?.parent_id).toBe(group.id);
});

it("同级里拖动排序:⌘Z 一步回到原样(走的是同一条撤销栈)", async () => {
  await open();
  drag(group.id, plane().id, AT.before);
  expect(visible()).toEqual(["后排", "内隔断", "石像", name(plane().id), name(camera().id)]);
  act(() => {
    fireEvent.keyDown(document.body, { key: "z", code: "KeyZ", metaKey: true });
  });
  expect(visible()).toEqual([name(plane().id), name(camera().id), "后排", "内隔断", "石像"]);
});

it("拖进组:parent_id 换成那个组", async () => {
  await open();
  drag(plane().id, group.id, AT.inside);
  // 地面成了「后排」的孩子,排在那一桶的末尾(内隔断、石像之后)。
  expect(visible()).toEqual([name(camera().id), "后排", "内隔断", "石像", name(plane().id)]);
  expect(levels()[name(plane().id)]).toBe("2");
  const after = await saved();
  expect(after.content.objects.find((one) => one.name === name(plane().id))?.parent_id).toBe(group.id);
});

it("拖出组:落在顶层某一行上,parent_id 回到 null", async () => {
  await open();
  // 把「石像」拖到机位的后面 —— 那是根层的缝。
  drag(statue.id, camera().id, AT.after);
  expect(visible()).toEqual([name(plane().id), name(camera().id), "石像", "后排", "内隔断"]);
  expect(levels()["石像"]).toBe("1");
  const after = await saved();
  expect(after.content.objects.find((one) => one.name === "石像")?.parent_id).toBeNull();
});

it("拖到列表末尾那条空白:回到最外层,接在根层最后", async () => {
  await open();
  drag(statue.id, "__scene-root__", AT.after);
  expect(visible()).toEqual([name(plane().id), name(camera().id), "后排", "内隔断", "石像"]);
  expect(levels()["石像"]).toBe("1");
  const after = await saved();
  expect(after.content.objects.find((one) => one.name === "石像")?.parent_id).toBeNull();
});

it("落在叶子行的中间不会把它当父级:非组收不了,那一下只是在它旁边排序", async () => {
  await open();
  // 「石像」是叶子(不是组)。落在它中段:它没有"放进去"那一段,按上下半分 → 排在它后面,
  // 也就是挂到它所在的那个组下面 —— 父级永远是组,不会是盒子。
  drag(plane().id, statue.id, AT.inside);
  const after = await saved();
  const moved = after.content.objects.find((one) => one.id === plane().id);
  expect(moved?.parent_id).toBe(group.id);
  expect(after.content.objects.find((one) => one.id === statue.id)?.kind).toBe("box");
  expect(after.content.objects.some((one) => one.parent_id === statue.id)).toBe(false);
});

it("折叠着的组照样能落进去,落完自己展开(东西不会就此不见)", async () => {
  await open();
  fireEvent.click(screen.getByRole("button", { name: "收起 后排" }));
  expect(row(group.id)).toHaveAttribute("aria-expanded", "false");
  expect(visible()).toEqual([name(plane().id), name(camera().id), "后排"]);

  drag(plane().id, group.id, AT.inside);
  expect(row(group.id)).toHaveAttribute("aria-expanded", "true");
  expect(visible()).toEqual([name(camera().id), "后排", "内隔断", "石像", name(plane().id)]);
  const after = await saved();
  expect(after.content.objects.find((one) => one.id === plane().id)?.parent_id).toBe(group.id);
});

it("拖进自己的后代:落点根本画不出来,松手什么也不写", async () => {
  await open();
  hover(group.id, inner.id, AT.inside);
  // 环:一个落点都没有(连"禁止"那一档也没有 —— 不画就是落不下去)。
  expect(document.querySelectorAll("[data-drop]")).toHaveLength(0);

  drag(group.id, inner.id, AT.inside);
  expect(visible()).toEqual([name(plane().id), name(camera().id), "后排", "内隔断", "石像"]);

  // 什么都没变,也就没欠着要存的东西:⌘S 不该发出请求。
  saveAttempt();
  expect(saveScene).not.toHaveBeenCalled();
});

it("拖动中的样子:被拖的那一行淡下去,目标行画出落点(前后是一道线、放进去是描边)", async () => {
  await open();
  hover(plane().id, statue.id, AT.before);
  expect(row(plane().id)).toHaveAttribute("data-dragging");
  expect(row(statue.id)).toHaveAttribute("data-drop", "before");
  // 跟手的那一片写着在拖什么。
  expect(document.querySelector(".scene-object-ghost")?.textContent).toContain(name(plane().id));

  // 挪到组的中段:落点从"排在前面"变成"放进去",前一处落点收掉。
  act(() => dnd.onDragMove?.(event(plane().id, group.id, AT.inside)));
  expect(row(statue.id)).not.toHaveAttribute("data-drop");
  expect(row(group.id)).toHaveAttribute("data-drop", "inside");

  // 取消(松在空处):落点和"正在拖"都收掉。
  act(() => dnd.onDragCancel?.(event(plane().id, null, AT.inside)));
  expect(document.querySelectorAll("[data-drop]")).toHaveLength(0);
  expect(row(plane().id)).not.toHaveAttribute("data-dragging");
});

it("⌥↑ / ⌥↓:选中的物体在同级里挪一格(键盘走的是同一套落点判定)", async () => {
  await open();
  fireEvent.click(tree().getByText("后排"));
  act(() => {
    fireEvent.keyDown(document.body, { key: "ArrowUp", code: "ArrowUp", altKey: true });
  });
  expect(visible()).toEqual([name(plane().id), "后排", "内隔断", "石像", name(camera().id)]);
  // 组里的东西跟着走,层数没变。
  expect(levels()["石像"]).toBe("2");

  act(() => {
    fireEvent.keyDown(document.body, { key: "ArrowDown", code: "ArrowDown", altKey: true });
  });
  expect(visible()).toEqual([name(plane().id), name(camera().id), "后排", "内隔断", "石像"]);
});

it("每一行都注册成可落的,末尾那条空白也是 —— 只可拖不可落的话落点永远指不到", async () => {
  await open();
  const registered = new Set(dnd.droppables);
  for (const one of [plane().id, camera().id, group.id, inner.id, statue.id]) {
    expect(registered.has(one), `${name(one)} 不是落点`).toBe(true);
  }
  expect(registered.has("__scene-root__")).toBe(true);
});

it("标题里的 aria 还是那棵树:treeitem / 层级 / 展不展开", async () => {
  await open();
  expect(screen.getByRole("tree")).toBeInTheDocument();
  const rows = screen.getAllByRole("treeitem");
  // 没有折叠箭头的那两行也在(树里的每一行都是 treeitem)。
  expect(rows).toHaveLength(5);
  expect(row(group.id)).toHaveAttribute("aria-expanded", "true");
  expect(row(statue.id)).not.toHaveAttribute("aria-expanded");
});

const tree = () => within(screen.getByRole("tree"));
