/**
 * 系统的「选文件 / 选文件夹」对话框:连接页上本机服务的目录、解释器这类路径格旁边的「选择…」。
 *
 * 渲染层说要哪一种(`directory` / `file`)、对话框标题、从哪儿开始(格子里现在的值);主进程弹框,交回选中的那一个路径,
 * 取消是 null。交回去的只是一个字符串 —— 和人自己敲进去的一样,检查、确认照旧由后端那边做。
 */

/**
 * showOpenDialog 的选项。
 *
 * - 文件夹:可以当场新建一个(macOS 要 `createDirectory`;Windows 的选文件夹框自带「新建文件夹」);
 * - 文件:解释器多半在 `.venv` 这种点开头的目录里,所以显示隐藏文件;
 * - 都不解析别名 / 符号链接(`noResolveAliases`,macOS):`.venv/bin/python` 是指向基础解释器的链接,解析掉就丢了那个环境。
 */
function openDialogOptions({ kind, title, defaultPath, filters }) {
  const properties =
    kind === "directory"
      ? ["openDirectory", "createDirectory", "noResolveAliases"]
      : ["openFile", "showHiddenFiles", "noResolveAliases"];
  const options = { properties };
  if (title) options.title = title;
  if (defaultPath) options.defaultPath = defaultPath;
  if (kind === "file" && filters.length > 0) options.filters = filters;
  return options;
}

/** 弹框(挂在发起的那个窗口上;找不到窗口就不挂),交回选中的路径;取消或什么都没选是 null。 */
async function pickPath(dialog, window, request) {
  const options = openDialogOptions(request);
  const picked = window ? await dialog.showOpenDialog(window, options) : await dialog.showOpenDialog(options);
  if (picked.canceled) return null;
  return picked.filePaths[0] ?? null;
}

module.exports = { openDialogOptions, pickPath };
