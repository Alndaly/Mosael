/**
 * ADR 0081 P1:macOS 的只读 DesktopDriver。
 *
 * 枚举窗口(CGWindowList)、单窗口截图(`screencapture`)、AX 可访问性树(AXUIElement)。
 * 不注入任何输入(`act` 明确不支持);Swift 小工具按需编译一次,按源码哈希缓存。
 * 系统权限由 macOS 决定:缺 Screen Recording / Accessibility 时把真实错误交回去,不静默降级。
 */
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawn } = require("node:child_process");

const SOURCE = path.join(__dirname, "macosWindowTools.swift");
const MAX_OUTPUT = 8 * 1024 * 1024;

function run(command, args, timeout = 20000) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: ["ignore", "pipe", "pipe"] });
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

class DesktopDriverMac {
  /** `binaryPath` 仅供测试注入;生产从 Swift 源码编译并缓存。 */
  constructor({ cacheDir = path.join(os.tmpdir(), "mosael-window-tools"), binaryPath = null, runner = run } = {}) {
    this.cacheDir = cacheDir;
    this.binaryPath = binaryPath;
    this.runner = runner;
  }

  capabilities() {
    return { tree: true, screenshots: true, input: false, platforms: ["macos-window"] };
  }

  async binary() {
    return this.binaryPath ?? ensureBinary(this.cacheDir);
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
      return {
        image: fs.readFileSync(output).toString("base64"),
        width: size.pixelWidth,
        height: size.pixelHeight,
        elements: [],
        meta: { windowNumber: target.windowNumber },
      };
    }
    if (target.pid !== undefined) {
      const { stdout } = await this.runner(binary, ["ax", String(target.pid)]);
      const result = parse(stdout);
      return { elements: result.elements ?? [], meta: { pid: target.pid, snapshot_id: result.snapshot_id } };
    }
    return this.windows();
  }

  async act() {
    throw new Error("act_not_supported");
  }

  verify() {
    return { ok: false, reason: "verify_not_supported", evidence: null };
  }
}

module.exports = { DesktopDriverMac };
