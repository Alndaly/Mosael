/**
 * 画板画布的视口动作和标记(位置书签):居中到看得见的那块、查找跳转、放 / 改 / 删 / 跳标记。
 * 从 BoardCanvas 拆出来的钩子;事实来源仍是画布的 React Flow 节点。
 */
import React from "react";
import { toast } from "sonner";
import type { Node, ReactFlowInstance } from "@xyflow/react";

import { useI18n } from "@/app/preferences";
import { centerCanvasViewport, visibleCanvasSize, type CanvasViewportInsets } from "@/components/app/fitCanvasViewport";
import { LAYERS, searchFocusZoom } from "@/features/boards/boardCanvasModel";
import {
  MARKER_PREFIX,
  MAX_MARKERS,
  newMarkerId,
  nextMarkerName,
  toMarkerNodes,
  type CanvasMarker,
} from "@/features/markers/markers";
import { useMarkerShortcuts } from "@/features/markers/useMarkerShortcuts";

export function useBoardViewport({
  nodes,
  setNodes,
  rf,
  surface,
  getInsets,
  onRevealMarkers,
  commentMode,
}: {
  nodes: Node[];
  setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
  rf: React.RefObject<ReactFlowInstance | null>;
  surface: React.RefObject<HTMLDivElement | null>;
  getInsets?: (surface: HTMLElement) => CanvasViewportInsets;
  onRevealMarkers?: () => void;
  commentMode: boolean;
}) {
  const t = useI18n();
  // ── 标记(位置书签)────────────────────────────────────────────────────────
  //: 事实来源和画板项一样是 React Flow 的 nodes —— 拖动、选中、⌫ 删除因此全是白拿的,
  //: 撤销/重做也一样(历史存的是整份 toCanvas 快照,里面本来就带着 markers)。
  //: **经序列化取回一份稳定引用。** 这份清单要交给工具条(见 onReady 那条 effect),而
  //: `nodes` 每拖一帧就换一次身份 —— 直接 map 出来的话,拖任何一个节点都会让工具条跟着
  //: 重挂一遍。标记至多几十个,序列化的代价远小于每帧一次的重渲染。
  const markerKey = React.useMemo(
    () => JSON.stringify(nodes.filter((node) => node.type === "marker").map((node) => ({
      ...(node.data as unknown as { marker: CanvasMarker }).marker,
      x: Math.round(node.position.x),
      y: Math.round(node.position.y),
    }))),
    [nodes],
  );
  const markers = React.useMemo(() => JSON.parse(markerKey) as CanvasMarker[], [markerKey]);

  const patchMarker = React.useCallback((next: CanvasMarker) => {
    setNodes((current) =>
      current.map((node) => (node.id === MARKER_PREFIX + next.id ? { ...node, data: { ...node.data, marker: next } } : node)),
    );
  }, [setNodes]);

  const deleteMarker = React.useCallback((id: string) => {
    setNodes((current) => current.filter((node) => node.id !== MARKER_PREFIX + id));
  }, [setNodes]);

  /** 画布上没被右栏盖住的那块。页面没给就是整块。 */
  const insetsOf = React.useCallback(
    (pane: HTMLElement): CanvasViewportInsets => getInsets?.(pane) ?? {},
    [getInsets],
  );

  /**
   * 把一个流坐标点摆到**看得见的那块**的正中。
   *
   * 不是 `instance.setCenter` —— 它照整块画布居中,而右栏的智能体是盖在画布上的:
   * 目标正好落在它底下,看着像"点了没反应"。跳标记、跳评论都从这里走。
   */
  const centerOn = React.useCallback((point: { x: number; y: number }) => {
    const instance = rf.current;
    const pane = surface.current;
    if (!instance || !pane) return;
    void centerCanvasViewport(instance, pane, point, insetsOf(pane), {
      zoom: Math.max(instance.getZoom(), 0.9),
      duration: 350,
    });
  }, [insetsOf]);

  /** 跳到某个标记。视口居中过去,不改选中态 —— 跳转是"我要看那儿",不是"我要改那个"。
   *  **先把标记显示出来**:快捷键和清单两个入口都走这里 —— 此前只有清单那一处记得显示,按快捷键跳过去
   *  落在一块看不见旗子的地方。 */
  const jumpToMarker = React.useCallback((marker: CanvasMarker) => {
    onRevealMarkers?.();
    // 加半枚旗子:节点坐标是左上角,照它居中的话旗子整个偏在右下。
    centerOn({ x: marker.x + 60, y: marker.y + 14 });
  }, [centerOn, onRevealMarkers]);

  useMarkerShortcuts(markers, jumpToMarker, !commentMode);

  /** 查找节点跳到某一项。和跳标记一样只动视口、不改选中态 —— 按 Enter 一路往下看的时候,
   *  每一格都弹出自己的面板会把画布盖满。 */
  const focusItem = React.useCallback((itemId: string) => {
    const instance = rf.current;
    const pane = surface.current;
    const node = instance?.getNode(itemId);
    if (!instance || !pane || !node) return;
    const size = {
      width: node.measured?.width ?? node.width ?? 200,
      height: node.measured?.height ?? node.height ?? 120,
    };
    const insets = insetsOf(pane);
    void centerCanvasViewport(
      instance,
      pane,
      { x: node.position.x + size.width / 2, y: node.position.y + size.height / 2 },
      insets,
      {
        zoom: searchFocusZoom(instance.getZoom(), size, visibleCanvasSize(pane.clientWidth, pane.clientHeight, insets)),
        duration: 350,
      },
    );
  }, [insetsOf]);

  /** 这一块(流坐标)有没有哪怕一部分落在**看得见的那块**里(除去被右栏盖住的)。量不了的时候当它看得见。 */
  const isInView = React.useCallback((rect: { x: number; y: number; width: number; height: number }): boolean => {
    const instance = rf.current;
    const pane = surface.current;
    if (!instance || !pane || !pane.clientWidth) return true;
    const { x, y, zoom } = instance.getViewport();
    const insets = insetsOf(pane);
    const left = ((insets.left ?? 0) - x) / zoom;
    const top = ((insets.top ?? 0) - y) / zoom;
    const right = (pane.clientWidth - (insets.right ?? 0) - x) / zoom;
    const bottom = (pane.clientHeight - (insets.bottom ?? 0) - y) / zoom;
    return rect.x < right && rect.x + rect.width > left && rect.y < bottom && rect.y + rect.height > top;
  }, [insetsOf]);

  /** 在当前视口中心放一枚标记。放在**看得见的地方**:标记标的是"我现在在看的这块地方"。 */
  const addMarker = React.useCallback((point?: { x: number; y: number }) => {
    const instance = rf.current;
    const pane = surface.current;
    if (!instance || !pane) return;
    let placed = false;
    setNodes((current) => {
      const existing = current
        .filter((node) => node.type === "marker")
        .map((node) => (node.data as unknown as { marker: CanvasMarker }).marker);
      if (existing.length >= MAX_MARKERS) return current;
      // 同样避开右栏:一枚落在智能体底下的标记,加完就看不见。
      const rect = pane.getBoundingClientRect();
      const visible = visibleCanvasSize(pane.clientWidth, pane.clientHeight, insetsOf(pane));
      const center = point ?? instance.screenToFlowPosition({
        x: rect.left + visible.left + visible.width / 2,
        y: rect.top + visible.top + visible.height / 2,
      });
      const marker: CanvasMarker = {
        id: newMarkerId(existing),
        name: nextMarkerName(t("markers"), existing),
        x: Math.round(center.x),
        y: Math.round(center.y),
      };
      placed = true;
      return [...current.map((node) => ({ ...node, selected: false })), ...toMarkerNodes([marker], LAYERS.marker).map((node) => ({ ...node, selected: true }))];
    });
    if (!placed) toast.error(t("markerLimit").replace("{n}", String(MAX_MARKERS)));
  }, [setNodes, t, insetsOf]);

  return { markers, patchMarker, deleteMarker, insetsOf, centerOn, jumpToMarker, focusItem, isInView, addMarker };
}
