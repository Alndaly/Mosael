/**
 * 状态列表要不要接着问。
 *
 * 两个判据,都是"还有没答完的问题":
 *   - 正在下载 / 正在安装 → 状态在变
 *   - 还没探完运行环境(runtime_checked=false)→ 答案在后台的路上
 *
 * 第二条是探测挪到后台之后**必须**补的一半:值变成最终一致了,而界面若没有理由再问一次,
 * 那句「正在检查运行环境…」就会一直挂着。用户报的正是这个。
 *
 * 三张卡(转写模型 / 声音克隆 / 分离引擎)共用这一份 —— 同一条规则写三遍,下次只会改一遍。
 */
export function pollWhileUnsettled(
  rows: readonly { status?: string; runtime_checked?: boolean }[] | undefined,
): number | false {
  const list = rows ?? [];
  //: "installing" 是分离引擎那一页的说法(它装的是运行环境,不下模型),同样是"还在变"。
  if (list.some((row) => row.status === "downloading" || row.status === "installing")) return 1200;
  return list.some((row) => row.runtime_checked === false) ? 800 : false;
}
