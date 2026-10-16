import { assetFileUrl, assetPreviewUrl, type Asset } from "@/api/domains/assets";
import type { ExternalOpenBehavior } from "@/app/preferencesContext";
import type { ImagePreviewItem } from "@/components/app/imagePreviewContext";

/**
 * 从系统那边交过来的文件(「打开方式」、拖到程序坞 / 任务栏图标上)按偏好怎么处理。
 *
 * ── 「打开预览」为什么也是「导入 + 立刻预览」,而不是直接预览那份本地文件 ────────────────────
 *
 * 查过渲染层能不能预览一份**不在素材库里**的本地文件,结论是**不能**,四条证据:
 *
 * 1. 预览这一层只吃素材行的地址。`ImagePreviewItem` 的 `src` 在库里每一个调用点都是后端那条
 *    `/api/assets/{id}/…`(`assetPreviewUrl` / `assetFileUrl`)或者 `blob:` / `data:` 拼出来的
 *    (见 components/app/asset-preview、features/agent/MediaPreview、features/media/*);
 *    `assetId` 这个字段本身就是"这是库里哪一份"的意思 —— 灯箱顶上「保存到本地」按它取原始字节。
 * 2. 没有把绝对路径变成可加载地址的桥。preload 暴露的 `MosaelDesktopBridge` 里没有任何
 *    路径 → URL 的东西(见 electron/preload-api.d.ts),渲染层拿到的只是一串本机绝对路径。
 * 3. 就算拼一个 `file://` 也不成立:开发时窗口加载的是 `http://127.0.0.1:5173`,Chromium 会
 *    拦掉从 http 页面去取 `file://` 的子资源;`webPreferences` 里没有关掉 webSecurity
 *    (见 electron/main.cjs)。打包版加载 dist 走的是 file:// 文档,可那是另一回事,不能拿它
 *    当开发时也成立。
 * 4. 灯箱自己也只画两种东西:图(`<img>` 走 `src`)和视频(`video: true` → VideoPlayer)。
 *    音频没有第三种渲染 —— 所以音频在这条路上只有入库那一半,不该塞进画廊变成一张裂图。
 *
 * 于是这条路只能是:先入库(拿到素材行),再拿那一行去开灯箱。设置里的说明文字据实写着这一点,
 * 免得让人以为"打开预览"没有入库。
 *
 * ── 偏好什么时候生效 ────────────────────────────────────────────────────────────────
 *
 * `behavior` 是**调用时传进来的值**:正在跑的那一批按开跑时的值走完,改偏好只影响接下来那批
 * (见测试里最后一条)。这条也是给用户的那句话:「改完从下一个打开的文件起生效」。
 */
export type ExternalOpenDeps = {
  /** 入库一个路径,拿到那条素材。抛错 = 这一条没进来。 */
  importFile: (path: string) => Promise<Asset>;
  /** 立刻打开预览:全局灯箱那一层的入口(见 components/app/image-preview)。 */
  preview: (items: ImagePreviewItem[], startIndex: number) => void;
  /** 这一批入库的结果(成功几个、失败几个)。**两种偏好下都会报** —— 入库模式下它就是现状那句 toast。 */
  reportImport: (imported: number, failed: number) => void;
};

/** 灯箱画得出来的种类。文档、音频不在这里。 */
const PREVIEWABLE = new Set(["image", "video"]);

export async function openExternalFiles(
  paths: readonly string[],
  behavior: ExternalOpenBehavior,
  deps: ExternalOpenDeps,
): Promise<void> {
  //: **一次全发出去,按原顺序收结果** —— 一串文件不该一条一条等着导。失败的留在原地,不影响别的。
  const settled = await Promise.allSettled(paths.map((path) => deps.importFile(path)));
  const assets = settled.flatMap((one) => (one.status === "fulfilled" ? [one.value] : []));
  deps.reportImport(assets.length, settled.length - assets.length);

  if (behavior !== "preview") return;
  const items = assets.filter((one) => PREVIEWABLE.has(one.kind)).map(previewItem);
  //: 一条能预览的都没有(只有音频、或者全失败)时不开 —— 一个空灯箱比不开更让人摸不着头脑。
  if (items.length) deps.preview(items, 0);
}

function previewItem(asset: Asset): ImagePreviewItem {
  const item = { title: asset.name, assetId: asset.id };
  //: 图用后端转好的预览(HEIC 这类原图浏览器解不了),视频用原文件 —— 和素材库、
  //: 消息里的媒体卡、AI 工作台是同一套取址(见 api/domains/assets 的说明)。
  return asset.kind === "video"
    ? { ...item, src: assetFileUrl(asset.id), video: true }
    : { ...item, src: assetPreviewUrl(asset.id) };
}
