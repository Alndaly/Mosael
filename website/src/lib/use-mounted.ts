import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

/**
 * 服务端和水合那一帧是 false,之后是 true。
 *
 * 用来挡住只有浏览器才知道的东西(用户的主题、portal 的挂载点),免得 hydration 不一致。
 * 不用「effect 里 setMounted(true)」:那是渲染完再同步改一次状态,多一轮级联渲染;
 * useSyncExternalStore 的 server snapshot 正是给这种「两端取值不同」准备的。
 */
export function useMounted(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
}
