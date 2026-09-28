import { errorText } from "@/api/errorMessage";
import type { MessageKey } from "@/app/messages";

/** 没导入进来的一个文件:叫什么、为什么。 */
export interface ImportFailure {
  name: string;
  reason: string;
}

/**
 * 一批本机文件**逐个**导入,一个失败不拦后面的。素材库与剪辑页素材池(features/media/useImportMediaFiles)、
 * 画板拖放 / 粘贴、参考图墙上传都调这一个,不各写循环。
 *
 * **永不 reject**:每个文件的失败都收进 `failed`,调用方只在 onSuccess 里按结果说话,不必另写 onError。
 *
 * 为什么不让整批抛错:第三个格式不支持时,前两个其实已经进了素材库 —— 整批失败会让它们既不上画板、
 * 也不刷新素材库的缓存,看起来像什么都没发生。**逐个传,不并发**:一次十个视频,并发会把带宽和
 * 后端的转码队列同时打满。
 */
export async function importEach<T>(
  files: readonly File[],
  importOne: (file: File) => Promise<T>,
): Promise<{ imported: T[]; failed: ImportFailure[] }> {
  const imported: T[] = [];
  const failed: ImportFailure[] = [];
  for (const file of files) {
    try {
      imported.push(await importOne(file));
    } catch (error) {
      failed.push({ name: file.name, reason: errorText(error) });
    }
  }
  return { imported, failed };
}

/** 有没进来的时怎么说:进来几个、几个没进来、第一个为什么。全进来了回 null(成功的反馈由各处自己给)。 */
export function importFailureText(
  t: (key: MessageKey) => string,
  imported: number,
  failed: readonly ImportFailure[],
): string | null {
  const first = failed[0];
  if (!first) return null;
  return t("mediaImportPartial")
    .replace("{n}", String(imported))
    .replace("{m}", String(failed.length))
    .replace("{name}", first.name)
    .replace("{reason}", first.reason);
}
