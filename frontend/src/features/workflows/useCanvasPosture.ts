import React from "react";

/**
 * 画布**现在什么姿态** —— 是否已完成首次 fitView、视口动过几次、此刻正不正在平移。
 *
 * 抽出来是因为这三个 state 和工作流本身没有一点关系:它们是 React Flow 这个画布的机制,
 * 而 WorkflowEditor 里另外十四个 state 谈的是图、弹窗和搜索。混在一起时,读的人要先分辨
 * `viewportTick` 到底是业务概念还是渲染细节 —— 它是后者,而这一层区分本来就该由文件边界给出。
 *
 * 三条各自都有代价明确的来历,搬家时原样带走:
 */
export interface CanvasPosture {
  /** 首次 fitView 之前画布是藏着的 —— 挂载首帧节点在默认视口的错误位置,直接可见会闪一下。 */
  ready: boolean;
  /** 视口动过的次数。贴靠面板按节点的**屏幕**位置摆放,视口一动就要重算(平移/缩放时跟着节点走)。 */
  tick: number;
  /**
   * 此刻正在平移。
   *
   * 平移时贴靠面板会跟着节点走 —— 一旦它滑到指针底下,浏览器会对这次手势发 `pointercancel`,
   * 而 React Flow 的平移(d3-zoom)把 pointercancel 当作手势结束,于是**画布自己停住了**。
   * 面板在平移期间不吃指针事件(`inert`)就不会发生这件事:它照样跟着节点动,只是不拦。
   */
  panning: boolean;
  /** 挂到 `<ReactFlow>` 上的那几个回调。摊平成一组而不是让调用方自己接,免得漏一个。
   *  `onInit` 只负责标记就绪 —— fitView 由调用方在同一处做,那是它的策略不是画布姿态。 */
  handlers: {
    onInit: () => void;
    onMoveStart: () => void;
    onMove: () => void;
    onMoveEnd: () => void;
  };
}

export function useCanvasPosture(): CanvasPosture {
  const [ready, setReady] = React.useState(false);
  const [tick, setTick] = React.useState(0);
  const [panning, setPanning] = React.useState(false);

  const handlers = React.useMemo(
    () => ({
      onInit: () => setReady(true),
      onMoveStart: () => setPanning(true),
      onMove: () => setTick((n) => n + 1),
      onMoveEnd: () => setPanning(false),
    }),
    [],
  );

  return { ready, tick, panning, handlers };
}
