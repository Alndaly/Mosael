/**
 * 「保存到本地」:弹**系统保存框**,把渲染层一块块交来的字节写到用户当场选的那个位置。
 *
 * 为什么不接着用网页那套锚点下载:锚点的 `download` 属性在**跨域**时会被忽略(前端在 5173 / file://,
 * 文件端点在 8800),Electron 于是先导航到那个地址 —— 界面上先冒出一个空白页,下载才落下来。
 * 现在改成:渲染层先 fetch 出字节(登录态在它手里,不必让主进程自己带 cookie),经 IPC 交过来;
 * 主进程只做两件事 —— 弹框、往用户选的路径写。
 *
 * 安全:**路径只由保存框产生**。渲染层送进来的是一个建议文件名(见 ipc-contract.parseSaveFileBegin)
 * 和一块块字节,一个路径字符串都送不进来 —— 这里再把它压成一段安全的文件名,拼在系统的下载目录下当默认值。
 * 目标路径确认之后,写的是目标旁边那个 `<目标>.<pid>.<时刻>.partial`,收尾时才改名到位:取消、中途失败、
 * 渲染层没了,原来那个文件都一个字节没动。
 *
 * 为什么分四步(begin / write / end / abort)而不是一把把整份交过来:素材原文件可以有 2 GiB
 * (见 browser/pool/downloadRules.MAX_DOWNLOAD_BYTES),一条 IPC 消息装不下那么多字节,渲染层也不该为了存一个
 * 文件先把整份读进内存 —— 一块最多 8 MiB(见 ipc-contract.MAX_SAVE_CHUNK),流由渲染层自己拉
 * (fetch 的 body 或 Blob 的 stream),主进程这边只碰这一块。
 */
const fs = require("node:fs");
const path = require("node:path");
const { randomUUID } = require("node:crypto");

/** 一份写到一半的会话多久没人碰就撤掉:渲染层中途没了(刷新、崩),别把临时文件永远留在他选的那一格旁边。 */
const IDLE_MS = 10 * 60_000;
/** 同时最多几份没写完的。每次保存一个临时文件 —— 渲染层正常时同时只有一两份,给点余量但不放任。 */
const MAX_SESSIONS = 8;

/** 渲染层的说法(`Error: EACCES: ...`)原样给回去:失败原因得是能查的那一句,不是「保存失败」。 */
function reason(error) {
  return error && error.message ? String(error.message) : String(error);
}

/**
 * 建议文件名 → 系统上能用的那一段。路径分隔符、Windows 不收的字符换掉,开头的点和结尾的点 / 空格去掉
 * (`..`、`.hidden`、Windows 上结尾的点都会被系统当成别的东西),再长的截到 180;什么都不剩就退回一个通用名。
 * `safeName("../../evil.txt")` 是 `_.._evil.txt` —— 它在下载目录里面,出不去。
 */
function safeName(raw) {
  const cleaned = String(raw)
    .replace(/[<>:"/\\|?*\x00-\x1f]/g, "_")
    .trim()
    .replace(/^\.+/, "")
    .replace(/[. ]+$/, "");
  return cleaned.slice(0, 180) || "mosael-download";
}

/**
 * 保存框的选项。默认名是建议名,默认目录是**系统的下载目录**;`properties` 两样都是「别让用户意外覆盖」:
 * macOS 当场能新建文件夹,Linux 上覆盖前先问一句(Windows / macOS 的覆盖确认是系统自带的)。
 */
function saveDialogOptions(title, defaultPath) {
  return { title, defaultPath, properties: ["showOverwriteConfirmation", "createDirectory"] };
}

/**
 * 一份保存会话的台账。`downloadsDir` 由主进程给(app.getPath("downloads")),`dialog` 就是 electron 的
 * dialog —— 两者都从外面递进来,测试才好把它们换掉(见 save-file.test.ts)。
 */
function createSaveDesk({ dialog, downloadsDir, title, idleMs = IDLE_MS, log = () => {} }) {
  /** 写到一半的:目标路径、临时文件、已经写了多少、闲置计时器。 */
  const sessions = new Map();

  /** 撤掉一份会话:关掉句柄、删掉临时文件。**不碰目标路径** —— 用户原来那个文件原样在那儿。 */
  async function discard(session) {
    clearTimeout(session.timer);
    sessions.delete(session.id);
    await session.handle.close().catch(() => undefined);
    await fs.promises.rm(session.partial, { force: true }).catch(() => undefined);
  }

  function touch(session) {
    clearTimeout(session.timer);
    session.timer = setTimeout(() => {
      log(`idle, discarded ${path.basename(session.partial)}`);
      void discard(session);
    }, idleMs);
    // 别让一个还没写完的保存把应用留在那儿不退出。
    session.timer.unref?.();
  }

  /**
   * 第一步:弹系统保存框,选好了就开一个临时文件等着写。**取消是 `cancelled`,不是错误** ——
   * 调用方静默收场,不弹框、不提示。
   */
  async function begin(request, window) {
    if (sessions.size >= MAX_SESSIONS) {
      return { status: "failed", error: `too many saves in flight (${MAX_SESSIONS})` };
    }
    const target = path.join(downloadsDir, safeName(request.name));
    const options = saveDialogOptions(title, target);
    let picked;
    try {
      picked = window ? await dialog.showSaveDialog(window, options) : await dialog.showSaveDialog(options);
    } catch (error) {
      return { status: "failed", error: reason(error) };
    }
    if (picked.canceled || !picked.filePath) return { status: "cancelled" };
    const id = randomUUID();
    const session = {
      id,
      filePath: picked.filePath,
      partial: `${picked.filePath}.${process.pid}.${Date.now()}.partial`,
      handle: null,
      received: 0,
      timer: null,
    };
    try {
      // `wx`:临时名是刚拼的,但同一毫秒里撞上了就别往下走(宁可报错,也不覆盖别人的文件)。
      session.handle = await fs.promises.open(session.partial, "wx");
    } catch (error) {
      return { status: "failed", error: reason(error) };
    }
    sessions.set(id, session);
    touch(session);
    log(`begin ${path.basename(session.filePath)}`);
    return { status: "ready", id };
  }

  /** 第二步:写一块。失败就把这份会话撤了(不留给下一次写一个坏句柄)。 */
  async function write({ id, bytes }) {
    const session = sessions.get(id);
    if (!session) return { status: "failed", error: "this save is no longer open" };
    try {
      await session.handle.write(bytes);
      session.received += bytes.byteLength;
      touch(session);
      return { status: "writing", received: session.received };
    } catch (error) {
      await discard(session);
      log(`write failed ${path.basename(session.filePath)}: ${reason(error)}`);
      return { status: "failed", error: reason(error) };
    }
  }

  /** 第三步:收尾。临时文件改名到用户选的那个路径上(和 data:createBackup 同一个做法)。 */
  async function end({ id }) {
    const session = sessions.get(id);
    if (!session) return { status: "failed", error: "this save is no longer open" };
    clearTimeout(session.timer);
    sessions.delete(id);
    try {
      await session.handle.close();
      await fs.promises.rm(session.filePath, { force: true });
      await fs.promises.rename(session.partial, session.filePath);
    } catch (error) {
      await fs.promises.rm(session.partial, { force: true }).catch(() => undefined);
      log(`write failed ${path.basename(session.filePath)}: ${reason(error)}`);
      return { status: "failed", error: reason(error) };
    }
    log(`saved ${path.basename(session.filePath)} (${session.received} bytes)`);
    return { status: "saved", path: session.filePath };
  }

  /** 撤销:关掉、删掉临时文件。用户选的那个路径不碰。 */
  async function abort({ id }) {
    const session = sessions.get(id);
    if (session) await discard(session);
  }

  /** 退出时把还挂着的都撤掉(见 main.cjs 的 will-quit)。 */
  async function dispose() {
    await Promise.all([...sessions.values()].map((session) => discard(session)));
  }

  return { begin, write, end, abort, dispose, count: () => sessions.size };
}

module.exports = { MAX_SESSIONS, createSaveDesk, safeName, saveDialogOptions };
