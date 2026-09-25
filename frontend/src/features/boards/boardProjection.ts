/**
 * 画板详情页手上那份画布(本地投影)和服务端那份之间的两条规矩。
 */

/**
 * 两份画布是不是同一份 —— **按内容比,不按字段顺序**。
 *
 * 服务端按 normalize 的顺序写每一项的字段(id、kind、x、y、width、height、text、form、color…),
 * 而本地的项是一路 `{...item, text}` 长出来的:新建之后才写字的便签,text 排在 color 后面。
 * 直接比 JSON 串的话,这两份永远「不一样」—— 轮询于是认定本地有没存的改动,回执落地时不采用
 * 服务端那份,接着那次补丁触发的自动保存带着旧版本号撞 409:每出一张图就弹一次「有冲突」。
 */
export function sameCanvas(a: unknown, b: unknown): boolean {
  return canonical(a) === canonical(b);
}

function canonical(value: unknown): string {
  return JSON.stringify(value, (_key, one: unknown) =>
    one && typeof one === "object" && !Array.isArray(one)
      ? Object.fromEntries(Object.entries(one).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)))
      : one,
  );
}

/**
 * 一张板上的写请求排成一队:前一个回来、版本号推进之后,后一个才读版本号发出去。
 *
 * 每个写请求都带 base_revision 去 CAS。各发各的话,自动保存还在路上时点一下生成,两者带着
 * **同一个**旧版本号出门 —— 后到的那个必然 409:要么生成被挡回(用户以为没点中),要么
 * 自动保存被挡回、整块画布被服务端那份替掉,再弹一句「有冲突」。冲突的另一方是他自己。
 *
 * `task` 在轮到它时才被调用,所以它要在**函数体里**读版本号,不能在排队之前就读好。
 */
export function createWriteQueue(): <T>(task: () => Promise<T>) => Promise<T> {
  let tail: Promise<unknown> = Promise.resolve();
  return <T,>(task: () => Promise<T>): Promise<T> => {
    const run = tail.then(task);
    tail = run.catch(() => undefined);
    return run;
  };
}
