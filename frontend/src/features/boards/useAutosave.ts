import React from "react";

/**
 * 自动保存:值稳定下来之后才发一次请求。
 *
 * 画板上每拖一下都会改一次画布 —— 每次都发请求既打服务端也打自己(响应回来又触发一次
 * 重渲染)。所以攒一下再发。
 *
 * **两条边界比防抖本身更容易错,而且错了都不报错:**
 *
 *  · **刚加载进来的那一份不能保存回去。** 挂载时 value 从 null 变成服务端那份,这是一次
 *    "变化",不拦的话每次打开画板都会立刻回写一次 —— 服务端多一次无谓的写,而 updated_at
 *    变了会让「最近编辑」的排序乱掉:用户只是看了一眼,那张板就跳到最前面。
 *  · **卸载时把欠着的那次补上。** 用户拖完最后一下就切走,防抖窗口还没到 —— 不补的话
 *    那一下就丢了,而他看到的是"我明明拖过"。
 */
export function useAutosave<T>(
  value: T | null,
  save: (value: T) => void,
  delay = 600,
): { pending: boolean } {
  const [pending, setPending] = React.useState(false);
  //: 上一次**已经落定**的值(服务端那份,或刚存过的那份)。和它相同就没什么可存的。
  const settled = React.useRef<T | null>(null);
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  //: save 每次渲染都是新函数;用 ref 读当前的那个,免得把它塞进依赖里反复重建定时器。
  const saveRef = React.useRef(save);
  saveRef.current = save;
  //: 欠着还没发的那一次。卸载时补发。
  const owed = React.useRef<T | null>(null);

  React.useEffect(() => {
    if (value === null) return;
    if (settled.current === null) {
      // 第一次拿到值 = 加载完成,不是编辑。
      settled.current = value;
      return;
    }
    if (value === settled.current) return;

    owed.current = value;
    setPending(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const next = owed.current;
      owed.current = null;
      timer.current = null;
      if (next === null) return;
      settled.current = next;
      setPending(false);
      saveRef.current(next);
    }, delay);
  }, [value, delay]);

  React.useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
      // 卸载时把欠着的补上 —— 拖完最后一下就切走的那一次不能丢。
      const next = owed.current;
      owed.current = null;
      if (next !== null) saveRef.current(next);
    },
    [],
  );

  return { pending };
}
