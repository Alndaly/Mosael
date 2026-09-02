import React from "react";

/**
 * 自动保存:值稳定下来之后才发一次请求。
 *
 * 画板上每拖一下都会改一次画布 —— 每次都发请求既打服务端也打自己(响应回来又触发一次
 * 重渲染)。所以攒一下再发。
 *
 * **四条边界比防抖本身更重要:**
 *
 *  · **刚加载进来的那一份不能保存回去。** 挂载时 value 从 null 变成服务端那份,这是一次
 *    "变化",不拦的话每次打开画板都会立刻回写一次 —— 服务端多一次无谓的写,而 updated_at
 *    变了会让「最近编辑」的排序乱掉:用户只是看了一眼,那张板就跳到最前面。
 *  · **同一时刻只能有一次保存。** 旧请求比新请求更晚返回时,不能反过来覆盖新画布;
 *    请求期间的多次编辑只保留最新值。
 *  · **只有服务端确认才算落库。** Promise 失败后仍保持 pending,也不能把失败的值当成已保存。
 *  · **卸载时把欠着的那次补上。** 用户拖完最后一下就切走,防抖窗口还没到 —— 不补的话
 *    那一下就丢了,而他看到的是"我明明拖过"。
 */
export function useAutosave<T>(
  value: T | null,
  save: (value: T) => void | Promise<void>,
  delay = 600,
): { pending: boolean } {
  const [pending, setPending] = React.useState(false);
  //: 上一次**已被服务端确认**的值。请求只是发出去还不算落定。
  const confirmedValue = React.useRef<T | null>(null);
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  //: save 每次渲染都是新函数;用 ref 读当前的那个,免得把它塞进依赖里反复重建定时器。
  const saveRef = React.useRef(save);
  saveRef.current = save;
  //: 只留最新的待存值。旧值还在路上时继续编辑,中间态没有落库价值。
  const queuedValue = React.useRef<T | null>(null);
  const inFlight = React.useRef(false);
  const inFlightValue = React.useRef<T | null>(null);
  const mounted = React.useRef(true);
  const flushLatestRef = React.useRef<() => void>(() => undefined);

  flushLatestRef.current = () => {
    if (inFlight.current) return;
    const next = queuedValue.current;
    if (next === null) {
      if (mounted.current) setPending(false);
      return;
    }
    if (Object.is(next, confirmedValue.current)) {
      queuedValue.current = null;
      if (mounted.current) setPending(false);
      return;
    }

    queuedValue.current = null;
    inFlight.current = true;
    inFlightValue.current = next;

    const finish = (saved: boolean) => {
      const hasNewerValue = queuedValue.current !== null;
      if (saved) confirmedValue.current = next;
      // 失败值仍是用户最新的编辑时,必须留在队列里。不在这里
      // 无限重试:离线时会持续请求;下一次编辑或离开页面会再次刷新。
      if (!saved && !hasNewerValue) queuedValue.current = next;
      inFlight.current = false;
      inFlightValue.current = null;

      // 在请求飞行期间又改了画布,立即存最新的那份。如果又改回了刚被
      // 确认的值,则无需发一次重复请求。
      if (queuedValue.current !== null && Object.is(queuedValue.current, confirmedValue.current)) {
        queuedValue.current = null;
      }
      if (queuedValue.current !== null && (saved || hasNewerValue)) {
        flushLatestRef.current();
      } else if (mounted.current) {
        setPending(queuedValue.current !== null);
      }
    };

    try {
      const result = saveRef.current(next);
      if (result !== undefined && typeof result.then === "function") {
        void Promise.resolve(result).then(() => finish(true), () => finish(false));
      } else {
        finish(true);
      }
    } catch {
      finish(false);
    }
  };

  React.useEffect(() => {
    if (value === null) return;
    if (confirmedValue.current === null) {
      // 第一次拿到值 = 加载完成,不是编辑。
      confirmedValue.current = value;
      return;
    }
    const latest = queuedValue.current ?? inFlightValue.current ?? confirmedValue.current;
    if (Object.is(value, latest)) return;

    queuedValue.current = value;
    setPending(true);
    if (timer.current) clearTimeout(timer.current);
    if (inFlight.current) return;
    timer.current = setTimeout(() => {
      timer.current = null;
      flushLatestRef.current();
    }, delay);
  }, [value, delay]);

  React.useEffect(() => {
    // React StrictMode 在开发环境会执行 setup → cleanup → setup。每次 setup 都必须
    // 重新声明当前实例可以更新状态,不能让第一次演练性 cleanup 永久关掉它。
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (timer.current) clearTimeout(timer.current);
      // 卸载时把欠着的补上 —— 拖完最后一下就切走的那一次不能丢。
      // 已经在路上的请求结束后会自行继续刷新值;没在路上则现在就发。
      if (!inFlight.current) flushLatestRef.current();
    };
  }, []);

  return { pending };
}
