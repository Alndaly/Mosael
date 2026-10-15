/**
 * 文件夹从浏览器里出来的两条路(ADR 0059),到这里汇成同一个形状 `{name, files: [{file, path}]}`:
 *
 * - **选的**(`<input webkitdirectory>`):每个 File 带着 webkitRelativePath,第一段就是选中的那层文件夹。
 * - **拖进来的**:`dataTransfer.files` 里的文件夹只是一个读不出内容的空壳,得在 drop 那一刻(事件一过 items 就作废)
 *   用 webkitGetAsEntry 拿到入口,再一层层 readEntries 走下去。
 *
 * 系统垃圾在这里就丢掉,和后端(mosael_formats.agent_skill 的 JUNK_NAMES / JUNK_DIRS)同一张单子 —— 后端也会丢,
 * 这里先丢是不把一个 `.git` 整个传上去。总量封顶也在这里先挡一道:超了不传,省得传完 20MB 才被拒。
 */

/** 文件夹里的一个文件和它的相对路径(从最顶上那层文件夹名开始,像 webkitRelativePath)。 */
export interface FolderFile {
  file: File;
  path: string;
}

export interface PickedFolder {
  name: string;
  files: FolderFile[];
}

/** 和后端同一张垃圾单子(mosael_formats.agent_skill:JUNK_NAMES、JUNK_DIRS、`._` 开头的 AppleDouble)。 */
const JUNK_NAMES = new Set([".DS_Store", "Thumbs.db", "desktop.ini"]);
const JUNK_DIRS = new Set(["__MACOSX", ".git"]);

/** 一次最多传多少:后端 agent-bundles / skill-imports 收文件夹的上限(MAX_IMPORT_UPLOAD_BYTES、MAX_SKILL_FILES × MAX_SKILLS_PER_IMPORT)。 */
export const MAX_FOLDER_BYTES = 20 * 1024 * 1024;
export const MAX_FOLDER_FILES = 200 * 20;

export function isJunkPath(path: string): boolean {
  const parts = path.split("/").filter(Boolean);
  const last = parts[parts.length - 1] ?? "";
  return JUNK_NAMES.has(last) || last.startsWith("._") || parts.slice(0, -1).some((part) => JUNK_DIRS.has(part));
}

/** 超没超一次能传的量。 */
export function folderTooLarge(folder: PickedFolder): boolean {
  if (folder.files.length > MAX_FOLDER_FILES) return true;
  return folder.files.reduce((total, one) => total + one.file.size, 0) > MAX_FOLDER_BYTES;
}

/** `<input webkitdirectory>` 选到的文件 → 一个文件夹(选父目录时也是一个:最顶层就是选中的那层)。 */
export function folderFromInput(list: FileList | readonly File[] | null): PickedFolder | null {
  const files = Array.from(list ?? []).map((file) => ({
    file,
    path: (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name,
  }));
  if (!files.length) return null;
  return { name: files[0].path.split("/")[0] ?? "", files: files.filter((one) => !isJunkPath(one.path)) };
}

function readAll(reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> {
  //: readEntries 一次只给一批(Chrome 一批 100 个),读到空为止才是全部。
  return new Promise((resolve, reject) => {
    const all: FileSystemEntry[] = [];
    const next = () =>
      reader.readEntries((batch) => {
        if (!batch.length) return resolve(all);
        all.push(...batch);
        next();
      }, reject);
    next();
  });
}

const fileOf = (entry: FileSystemFileEntry) => new Promise<File>((resolve, reject) => entry.file(resolve, reject));

/** 一个拖进来的文件夹入口 → 文件夹。走到超量就停(调用方再用 folderTooLarge 判)。 */
export async function readDroppedFolder(root: FileSystemDirectoryEntry): Promise<PickedFolder> {
  const files: FolderFile[] = [];
  let bytes = 0;
  const walk = async (dir: FileSystemDirectoryEntry, prefix: string) => {
    for (const entry of await readAll(dir.createReader())) {
      if (files.length > MAX_FOLDER_FILES || bytes > MAX_FOLDER_BYTES) return;
      const path = `${prefix}/${entry.name}`;
      if (entry.isDirectory) {
        if (!JUNK_DIRS.has(entry.name)) await walk(entry as FileSystemDirectoryEntry, path);
      } else if (!isJunkPath(path)) {
        const file = await fileOf(entry as FileSystemFileEntry);
        bytes += file.size;
        files.push({ file, path });
      }
    }
  };
  await walk(root, root.name);
  return { name: root.name, files };
}

/**
 * drop 那一刻把拖进来的东西分成「文件」和「文件夹入口」。**必须同步调用**:事件处理一返回,dataTransfer.items 就清空了。
 * 拿不到入口的环境(老浏览器、测试里伪造的 dataTransfer)全当文件,和以前一样。
 */
export function splitDropped(transfer: DataTransfer): { files: File[]; folders: FileSystemDirectoryEntry[] } {
  const items = Array.from(transfer.items ?? []).filter((item) => item.kind === "file");
  const entries = items.map((item) => (typeof item.webkitGetAsEntry === "function" ? item.webkitGetAsEntry() : null));
  if (!entries.some((entry) => entry?.isDirectory)) return { files: Array.from(transfer.files ?? []), folders: [] };
  const files: File[] = [];
  const folders: FileSystemDirectoryEntry[] = [];
  items.forEach((item, index) => {
    const entry = entries[index];
    if (entry?.isDirectory) folders.push(entry as FileSystemDirectoryEntry);
    else {
      const file = item.getAsFile();
      if (file) files.push(file);
    }
  });
  return { files, folders };
}
