/**
 * 后端没了,这个进程也不该继续活着。
 *
 * sidecar 由后端 spawn,靠 stdin 收帧。正常退出路径是「stdin 关了就退」—— 而它在两种情况下
 * 到不了:
 *
 * 1. **stdin 永远不 EOF。** 管道的写端只要还被任何一个进程持有就不会关。后端自己 fork 出的
 *    别的子进程会继承这个 fd(POSIX 默认继承),于是后端被 SIGKILL 之后,只要那些孙子进程
 *    还在,sidecar 就收不到 EOF —— 一个 3.5MB 的 node 进程留在那儿,没人管,也没人看得见;
 * 2. **stdin EOF 了但事件循环没空。** 轮次是**故意不 await** 的(await 会让 stdin 停读),
 *    所以读循环结束时可能还挂着一次没返回的模型请求。那些 promise 把事件循环钉住,
 *    `main()` 返回之后进程照样不退。远端任务的轮询上限是六小时。
 *
 * 判据用 `process.ppid` 而不是「ping 得到后端吗」:父进程一死,内核立刻把孤儿挂到 init/launchd
 * 名下,ppid 变成 1(或 macOS 上的某个 launchd)。这是**内核给的事实**,不需要对方还能答话 ——
 * 而后端正是在"答不上话"的时候才需要这条。
 */

/** 多久看一次父进程还在不在。比一次网络超时短得多,又不至于每秒醒一次。 */
export const PARENT_CHECK_MS = 5_000;

export type LifetimeHooks = {
  ppid: () => number;
  exit: (code: number) => void;
  log: (...parts: unknown[]) => void;
  setInterval: (fn: () => void, ms: number) => { unref?: () => void };
};

/**
 * 盯住父进程。返回一个停表的函数(给测试和优雅退出用)。
 *
 * 定时器 `unref()`:它自己**不能**成为"进程还有事做"的理由,否则这条看门狗会把它要防的
 * 那件事变成必然 —— 一个永远不退的进程。
 */
export function watchParent(hooks: LifetimeHooks): () => void {
  const born = hooks.ppid();
  const timer = hooks.setInterval(() => {
    const now = hooks.ppid();
    if (now === born) return;
    hooks.log(`parent ${born} is gone (ppid is now ${now}); exiting`);
    hooks.exit(0);
  }, PARENT_CHECK_MS);
  timer.unref?.();
  return () => {
    // Node 的 clearInterval 认 Timeout 对象;测试传进来的假表自己带 unref。
    clearInterval(timer as unknown as NodeJS.Timeout);
  };
}
