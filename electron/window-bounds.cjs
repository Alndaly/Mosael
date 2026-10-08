"use strict";

/**
 * 记住主窗口在哪、多大,下次照原样打开。
 *
 * 此前每次都是 1440×900 居中:摆好的窗口重启就回去了;1366×768 的笔记本上一打开就超出屏幕。存的是「正常状态」的
 * 位置大小(最大化之前的那个)和是否最大化;全屏不记(那是一时的)。
 *
 * 恢复时要对得上**此刻**的显示器:外接屏拔了,存下的位置可能在一块已经不存在的屏上 —— 那就回到主屏居中;
 * 屏比上次小,就把大小夹进工作区。
 */
const fs = require("node:fs");

const FILE_NAME = "window-state.json";
/** 窗口至少要有这么一块露在某块屏的工作区里,才算「还看得见」(标题栏那一条够抓得住)。 */
const VISIBLE_MIN = { width: 160, height: 64 };

/**
 * @typedef {{ x: number, y: number, width: number, height: number }} Rect
 * @param {unknown} saved  上次存下的(可能是坏的、旧的、根本没有)
 * @param {{ workArea: Rect }[]} displays  此刻的显示器
 * @param {{ width: number, height: number, minWidth: number, minHeight: number }} defaults
 * @returns {{ bounds: Partial<Rect> & { width: number, height: number }, maximized: boolean }}
 */
function placeWindow(saved, displays, defaults) {
  const primary = displays[0]?.workArea ?? { x: 0, y: 0, width: defaults.width, height: defaults.height };
  const fitSize = (area, width, height) => ({
    width: Math.max(Math.min(defaults.minWidth, area.width), Math.min(Math.round(width), area.width)),
    height: Math.max(Math.min(defaults.minHeight, area.height), Math.min(Math.round(height), area.height)),
  });
  const centered = (area, size) => ({
    x: Math.round(area.x + (area.width - size.width) / 2),
    y: Math.round(area.y + (area.height - size.height) / 2),
    ...size,
  });
  const fallback = { bounds: centered(primary, fitSize(primary, defaults.width, defaults.height)), maximized: false };

  const s = /** @type {Record<string, unknown> | null} */ (saved && typeof saved === "object" ? saved : null);
  if (!s || ![s.x, s.y, s.width, s.height].every((n) => typeof n === "number" && Number.isFinite(n))) return fallback;
  const rect = { x: Number(s.x), y: Number(s.y), width: Number(s.width), height: Number(s.height) };
  const overlap = (area) => ({
    width: Math.min(rect.x + rect.width, area.x + area.width) - Math.max(rect.x, area.x),
    height: Math.min(rect.y + rect.height, area.y + area.height) - Math.max(rect.y, area.y),
  });
  const home = displays
    .map((display) => display.workArea)
    .find((area) => {
      const shared = overlap(area);
      return shared.width >= VISIBLE_MIN.width && shared.height >= VISIBLE_MIN.height;
    });
  if (!home) return { ...fallback, maximized: s.maximized === true };
  const size = fitSize(home, rect.width, rect.height);
  // 夹进那块屏的工作区:大小变了的话,位置也得跟着挪回来。
  const x = Math.min(Math.max(rect.x, home.x), home.x + home.width - size.width);
  const y = Math.min(Math.max(rect.y, home.y), home.y + home.height - size.height);
  return { bounds: { x: Math.round(x), y: Math.round(y), ...size }, maximized: s.maximized === true };
}

function readSaved(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

/**
 * 盯着窗口:挪动、改大小、最大化 / 还原之后(停半秒再)存一次;关窗(收进托盘)时马上存。
 * @param {import("electron").BrowserWindow} win
 * @param {string} file
 */
function rememberWindowBounds(win, file) {
  let timer = null;
  const save = () => {
    clearTimeout(timer);
    timer = null;
    if (win.isDestroyed() || win.isFullScreen() || win.isMinimized()) return;
    try {
      fs.writeFileSync(file, JSON.stringify({ ...win.getNormalBounds(), maximized: win.isMaximized() }));
    } catch {
      // 存不下去只是下次回到默认位置。
    }
  };
  const later = () => {
    clearTimeout(timer);
    timer = setTimeout(save, 500);
  };
  for (const event of ["resize", "move", "maximize", "unmaximize"]) win.on(event, later);
  win.on("close", save);
}

module.exports = { FILE_NAME, placeWindow, readSaved, rememberWindowBounds };
