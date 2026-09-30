// 具名浏览器会话的登录分区搬家(后端迁移写下搬家单,见后端 db.model_slices.browser.BrowserPartitionMove)。
//
// 分区名改过一次形状:旧的 `persist:rpa-<清洗后的名字>` 跨工作区共用、非 ASCII 名字撞成一个;新的是
// `persist:rpa-<工作区>-<名字哈希>`。已经登录过的数据在这台电脑的 userData 里 —— 只有这一侧知道那个目录
// 在哪,所以后端只算「谁搬到哪」,搬在这里做。
import { existsSync, mkdirSync, renameSync } from "node:fs";
import { join } from "node:path";

export interface PartitionMove {
  id: string;
  old_partition: string;
  new_partition: string;
}

export interface PartitionMoveOutcome {
  status: "done" | "skipped";
  reason: string;
}

/**
 * `persist:<名字>` 在磁盘上的目录:`<userData>/Partitions/<名字转小写>`(Electron 的 MakePartitionName
 * 先转小写再转义)。只认 `[a-z0-9_-]` —— 转义规则就不必抄一份;两条规则造出来的分区名都落在这个范围里,
 * 落不进来的说明这条搬家单不是它们造的,不碰。
 */
export function partitionDir(userData: string, partition: string): string | null {
  const match = /^persist:([a-z0-9_-]+)$/.exec(partition.toLowerCase());
  return match ? join(userData, "Partitions", match[1]) : null;
}

/**
 * 搬一条。**只在这个进程还没用过这两个分区时搬**(`inUse`):用着的分区目录里有打开的数据库文件,
 * 挪走之后 Chromium 还往旧句柄里写。新目录已经在了也不搬 —— 那是一份更新的登录,不拿旧的盖它。
 */
export function applyPartitionMove(
  userData: string,
  move: PartitionMove,
  inUse: (partition: string) => boolean = () => false,
): PartitionMoveOutcome | null {
  const from = partitionDir(userData, move.old_partition);
  const to = partitionDir(userData, move.new_partition);
  if (!from || !to) return { status: "skipped", reason: `unexpected partition name: ${move.old_partition} → ${move.new_partition}` };
  if (inUse(move.old_partition) || inUse(move.new_partition)) return null; // 下次启动再搬
  if (!existsSync(from)) return { status: "skipped", reason: `nothing on disk at ${from}` };
  if (existsSync(to)) return { status: "skipped", reason: `target already exists: ${to}` };
  try {
    mkdirSync(join(userData, "Partitions"), { recursive: true });
    renameSync(from, to);
  } catch (error) {
    return { status: "skipped", reason: `rename failed: ${error instanceof Error ? error.message : String(error)}` };
  }
  return { status: "done", reason: "" };
}
