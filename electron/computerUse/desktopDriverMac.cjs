/**
 * ADR 0081 P1:macOS 的只读 DesktopDriver。
 *
 * 枚举窗口(CGWindowList)、单窗口截图(`screencapture`)、AX 可访问性树(AXUIElement)。
 * P2 动作只接受已核对的一次性令牌或绑定截图,受保护应用直接拒绝;Swift 工具按源码哈希缓存。
 * 系统权限由 macOS 决定:缺 Screen Recording / Accessibility 时把真实错误交回去,不静默降级。
 */
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawn } = require("node:child_process");

const SOURCE = path.join(__dirname, "macosWindowTools.swift");
const MAX_OUTPUT = 8 * 1024 * 1024;
const SNAPSHOT_TTL_MS = 60_000;
const CAPTURE_TTL_MS = 60_000;
const MAX_BINDINGS = 8;
const PROTECTED_OWNERS = new Set([
  "1Password",
  "1Password 7",
  "Bitwarden",
  "Dashlane",
  "Keeper",
  "KeePassXC",
  "Keychain Access",
  "Passwords",
  "SecurityAgent",
  "System Settings",
  "System Preferences",
  "系统设置",
  "系统偏好设置",
  "Terminal",
  "终端",
  "iTerm2",
  "Warp",
  "loginwindow",
  "Keychain Access",
  "钥匙串访问",
  "Passwords",
  "密码",
]);

function run(command, args, timeout = 20000, input = null) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: [input === null ? "ignore" : "pipe", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => child.kill("SIGKILL"), timeout);
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
      if (stdout.length > MAX_OUTPUT) child.kill("SIGKILL");
    });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) reject(new Error(`${command} ${args.join(" ")} failed (${code}): ${stderr.trim()}`));
      else resolve({ stdout, stderr });
    });
    if (input !== null && child.stdin) child.stdin.end(input);
  });
}

async function ensureBinary(cacheDir) {
  const source = fs.readFileSync(SOURCE, "utf8");
  const hash = crypto.createHash("sha256").update(source).digest("hex").slice(0, 16);
  const target = path.join(cacheDir, `macos-window-tools-${hash}`);
  if (fs.existsSync(target)) return target;
  fs.mkdirSync(cacheDir, { recursive: true });
  const temporary = `${target}.tmp`;
  await run("xcrun", ["swiftc", "-O", SOURCE, "-o", temporary], 120000);
  fs.renameSync(temporary, target);
  fs.chmodSync(target, 0o755);
  return target;
}

function parse(stdout) {
  const parsed = JSON.parse(stdout);
  if (parsed && typeof parsed === "object" && parsed.error) {
    throw new Error(parsed.error.message || "macOS window tool failed");
  }
  return parsed;
}

const PERMISSION_KINDS = new Set(["accessibility", "screen"]);

function permissionRequired(kind) {
  const label = kind === "accessibility" ? "Accessibility" : "Screen Recording";
  const error = new Error(
    `macOS ${label} permission is required. Enable Mosael in System Settings → Privacy & Security → ${label}, then retry.`,
  );
  error.code = "desktop_permission_required";
  error.permission = kind;
  return error;
}

function bindingError(code, message) {
  const error = new Error(message);
  error.code = code;
  return error;
}

function elementFingerprint(element) {
  const frame = element?.frame ?? {};
  return JSON.stringify([
    element?.role ?? "",
    element?.title ?? "",
    Number(frame.x ?? 0),
    Number(frame.y ?? 0),
    Number(frame.width ?? 0),
    Number(frame.height ?? 0),
  ]);
}

function allowedOwner(owner) {
  if (PROTECTED_OWNERS.has(String(owner || ""))) {
    throw bindingError("desktop_protected_app", `Desktop actions are blocked in ${owner}.`);
  }
}

function keepLatest(map, key, value) {
  map.delete(key);
  map.set(key, value);
  while (map.size > MAX_BINDINGS) map.delete(map.keys().next().value);
}

class DesktopDriverMac {
  /** `binaryPath` 仅供测试注入;生产从 Swift 源码编译并缓存。 */
  constructor({
    cacheDir = path.join(os.tmpdir(), "mosael-window-tools"),
    binaryPath = null,
    runner = run,
    permissionGuide = null,
  } = {}) {
    this.cacheDir = cacheDir;
    this.binaryPath = binaryPath;
    this.runner = runner;
    this.permissionGuide = permissionGuide;
    this.snapshots = new Map();
    this.captures = new Map();
  }

  capabilities() {
    return { tree: true, screenshots: true, input: true, platforms: ["macos-window"] };
  }

  async binary() {
    return this.binaryPath ?? ensureBinary(this.cacheDir);
  }

  /** 只查询,不触发系统授权弹窗。 */
  async permissions() {
    const binary = await this.binary();
    const { stdout } = await this.runner(binary, ["permissions"]);
    return parse(stdout);
  }

  /** 仅供用户明确点击「向系统申请」后调用;observe 不会偷偷申请。 */
  async requestPermission(kind) {
    if (!PERMISSION_KINDS.has(kind)) throw new TypeError(`Unsupported desktop permission: ${String(kind)}`);
    const binary = await this.binary();
    const { stdout } = await this.runner(binary, ["request-permission", kind]);
    return Boolean(parse(stdout).granted);
  }

  async requirePermission(kind) {
    let status = await this.permissions();
    if (status[kind]) return;
    if (this.permissionGuide) await this.permissionGuide(kind);
    status = await this.permissions();
    if (!status[kind]) throw permissionRequired(kind);
  }

  /** 枚举当前在屏窗口(CGWindowList,不需要 Screen Recording)。 */
  async windows() {
    const binary = await this.binary();
    const { stdout } = await this.runner(binary, ["windows"]);
    return parse(stdout);
  }

  /**
   * 观察:
   * - 不给参数:枚举窗口;
   * - `{ windowNumber }`:`screencapture` 拍这一张(尺寸由 `sips` 读取);
   * - `{ pid }`:读这个应用的 AX 树(一次性 snapshot_id + 元素令牌)。
   */
  async observe(target = {}) {
    const binary = await this.binary();
    if (target.windowNumber !== undefined) {
      await this.requirePermission("screen");
      // `screencapture`(CGWindowListCreateImage)是当前可靠的窗口截图路径:
      // SCScreenshotManager.captureImage 在本机命令行里会 CGS_REQUIRE_INIT 断言。
      // 先落盘再读回,尺寸用 `sips` 读,不猜。
      const output = path.join(os.tmpdir(), `mosael-window-${target.windowNumber}.png`);
      await this.runner("screencapture", ["-l", String(target.windowNumber), output]);
      const { stdout: dimensions } = await this.runner("sips", ["-g", "pixelWidth", "-g", "pixelHeight", output]);
      const size = Object.fromEntries(dimensions.trim().split("\n").filter((line) => line.includes(":")).map((line) => {
        const [key, value] = line.split(":");
        return [key.trim(), Number(value.trim())];
      }));
      const window = (await this.windows()).find((one) => one.id === target.windowNumber);
      if (!window || !window.onscreen || !(window.width > 0) || !(window.height > 0)) {
        throw new Error(`Desktop window ${target.windowNumber} is not visible; nothing was captured.`);
      }
      const captureId = crypto.randomUUID();
      keepLatest(this.captures, captureId, {
        windowNumber: target.windowNumber,
        pid: window.pid,
        owner: window.owner,
        x: window.x,
        y: window.y,
        width: window.width,
        height: window.height,
        imageWidth: size.pixelWidth,
        imageHeight: size.pixelHeight,
        scale: size.pixelWidth / window.width,
        at: Date.now(),
      });
      return {
        image: fs.readFileSync(output).toString("base64"),
        width: size.pixelWidth,
        height: size.pixelHeight,
        elements: [],
        meta: { windowNumber: target.windowNumber, capture_id: captureId },
      };
    }
    if (target.pid !== undefined) {
      await this.requirePermission("accessibility");
      const { stdout } = await this.runner(binary, ["ax", String(target.pid)]);
      const result = parse(stdout);
      const elements = result.elements ?? [];
      keepLatest(this.snapshots, result.snapshot_id, { pid: target.pid, elements, at: Date.now() });
      return { elements, meta: { pid: target.pid, snapshot_id: result.snapshot_id } };
    }
    return this.windows();
  }

  async resolveToken(token) {
    const match = /^([A-Za-z0-9-]+):(\d+)$/.exec(String(token || ""));
    if (!match) throw bindingError("desktop_token_invalid", "The desktop element token is invalid.");
    const snapshot = this.snapshots.get(match[1]);
    if (!snapshot || Date.now() - snapshot.at > SNAPSHOT_TTL_MS) {
      throw bindingError("desktop_stale_snapshot", "The accessibility snapshot expired; observe the app again.");
    }
    const index = Number(match[2]);
    const before = snapshot.elements[index];
    if (!before) throw bindingError("desktop_token_invalid", "The desktop element token is not in that snapshot.");
    const windows = await this.windows();
    const visible = windows.find((one) => one.pid === snapshot.pid && one.onscreen);
    if (!visible) {
      throw bindingError("desktop_target_not_visible", "The target app has no visible window right now.");
    }
    allowedOwner(visible.owner);
    const binary = await this.binary();
    const current = parse((await this.runner(binary, ["ax", String(snapshot.pid)])).stdout);
    const after = (current.elements ?? []).find((element) => element.path === before.path);
    if (!after || elementFingerprint(before) !== elementFingerprint(after)) {
      throw bindingError("desktop_stale_snapshot", "The target element changed; observe the app again before acting.");
    }
    const frame = after.frame;
    if (!frame || !(frame.width > 0) || !(frame.height > 0)) {
      throw bindingError("desktop_target_has_no_frame", "The target element has no clickable frame.");
    }
    return {
      pid: snapshot.pid,
      windowNumber: visible.id,
      binding: { kind: "snapshot", key: match[1] },
      point: { x: frame.x + frame.width / 2, y: frame.y + frame.height / 2 },
    };
  }

  async resolveCapture(captureId, x, y) {
    const capture = this.captures.get(String(captureId || ""));
    if (!capture || Date.now() - capture.at > CAPTURE_TTL_MS) {
      throw bindingError("desktop_stale_capture", "The desktop screenshot expired; take a new screenshot.");
    }
    const window = (await this.windows()).find((one) => one.id === capture.windowNumber);
    if (!window || !window.onscreen) {
      throw bindingError("desktop_target_not_visible", "The captured window is no longer visible.");
    }
    if (window.owner !== capture.owner || Math.abs(window.x - capture.x) > 0.5
        || Math.abs(window.y - capture.y) > 0.5 || Math.abs(window.width - capture.width) > 0.5
        || Math.abs(window.height - capture.height) > 0.5) {
      throw bindingError("desktop_stale_capture", "The window moved or resized; take a new screenshot.");
    }
    allowedOwner(capture.owner);
    if (!Number.isInteger(x) || !Number.isInteger(y) || x < 0 || y < 0
        || x >= capture.imageWidth || y >= capture.imageHeight) {
      throw bindingError("desktop_coordinate_invalid", "The click point is outside the desktop screenshot.");
    }
    return {
      pid: capture.pid,
      windowNumber: capture.windowNumber,
      binding: { kind: "capture", key: String(captureId) },
      point: {
        x: capture.x + x / capture.scale,
        y: capture.y + y / capture.scale,
      },
    };
  }

  async resolveTarget(action) {
    const token = String(action.token || "").trim();
    const captureId = String(action.captureId || "").trim();
    if (Boolean(token) === Boolean(captureId)) {
      throw bindingError("desktop_target_invalid", "Provide exactly one of token or captureId with x/y.");
    }
    return token ? this.resolveToken(token) : this.resolveCapture(captureId, action.x, action.y);
  }

  async act(action = {}) {
    if (!["click", "type", "scroll"].includes(action.kind)) {
      throw new TypeError(`Unsupported desktop action: ${String(action.kind)}`);
    }
    await this.requirePermission("accessibility");
    const target = await this.resolveTarget(action);
    //: 一次性绑定:动作一旦开始就作废 —— 即使 CGEvent 半途失败,也不许拿旧快照再点一次。
    (target.binding.kind === "snapshot" ? this.snapshots : this.captures).delete(target.binding.key);
    const request = {
      action: action.kind,
      pid: target.pid,
      point: target.point,
      button: action.button ?? "left",
      clickCount: action.clickCount ?? 1,
      text: action.text ?? "",
      dy: action.dy ?? 0,
    };
    const binary = await this.binary();
    const { stdout } = await this.runner(binary, ["perform"], 20000, JSON.stringify(request));
    const result = parse(stdout);
    return {
      kind: action.kind,
      windowNumber: target.windowNumber,
      pid: target.pid,
      point: result.point ?? target.point,
    };
  }

  verify() {
    return { ok: false, reason: "verify_not_supported", evidence: null };
  }
}

module.exports = { DesktopDriverMac };
