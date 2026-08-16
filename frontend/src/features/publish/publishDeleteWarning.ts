/**
 * 删一条发布记录时,警告该说哪一句。
 *
 * 已发布的记录是一份**对外行为的账**,和一条失败重试记录不是一回事:删掉它,平台上的内容
 * 不会被撤下,而「我发过什么」就此只剩记忆。确认框原本写的是「已产出的文件不受影响」——
 * 说的是本地文件,恰好避开了真正要紧的那半句。
 *
 * 批量删时只要选中的里面有一条发成功了,就按「发过」的说法警告:顺手删最容易把成功记录一起带走。
 */
export function deleteWarningKey(statuses: readonly string[]): string {
  return statuses.some((status) => status === "success") ? "publishDeleteBodyPublished" : "publishDeleteBody";
}
