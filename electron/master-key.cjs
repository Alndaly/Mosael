"use strict";

/**
 * 落盘加密的主密钥由系统钥匙串保管(后端 core/secrets_at_rest)。
 *
 * 此前桌面版的主密钥就放在数据目录里的 `secret.key`,和它要保护的数据库挨着:插件进程和后端是同一个系统用户,
 * 读得到它;备份 zip 也把它和数据库打在一起。现在:
 *
 * - 密钥用 Electron `safeStorage`(macOS 钥匙串、Windows DPAPI、Linux 的 libsecret / kwallet)封存成
 *   `<数据目录>/secret.key.sealed`。封存的文件离开这台机器、这个系统用户就解不开。
 * - 启动后端时**经标准输入**交给它(`MOSAEL_SECRET_KEY_STDIN=1`),不放环境变量 —— 同一用户的其他进程读得到
 *   另一个进程的环境变量。
 * - 老版本留下的明文 `secret.key`:封存一份、确认解得回同一把之后删掉明文。
 * - 系统没有可用的钥匙串(`isEncryptionAvailable()` 为假,常见于没有桌面密钥环的 Linux):不封存,
 *   后端照旧用数据目录里的 `secret.key`(没有就由这里先建好,两边拿到的是同一把)。那是如实的降级,不假装加了密。
 *   第一次封存时钥匙串出错同样降级成明文:那时还没有封存过的钥匙,明文就是唯一的那一把。
 * - **封存过的钥匙解不开**(用户在钥匙串提示上点了拒绝、钥匙串锁着或被重置、应用换了签名身份)**绝不降级**:
 *   明文在封存时就删了,这时让后端照常起来,它会另生一把新钥匙 —— 之后存的凭据用新钥匙加密,旧的那些再也解不开,
 *   而且界面没有壳令牌、连后端都连不上。所以抛 `SealedKeyUnavailableError`,由 `unlockMasterKey` 停下来问人
 *   (重试 / 去钥匙串授权 / 退出),问到解开为止或者退出,后端不起。
 *
 * 主密钥还派生出**壳令牌**(`shellToken`):打包版的界面从 file:// 加载,请求的 Origin 是 `null` —— 任何网页里的
 * sandboxed iframe 也是。壳在自己发往本机后端的请求上带 `X-Mosael-Shell: <shellToken>`,后端只放行带着它的
 * null 来源(backend app/core/shell_origin.py)。网页算不出它。
 */

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const PLAIN_NAME = "secret.key";
const SEALED_NAME = "secret.key.sealed";

/** 和 Python `cryptography.fernet.Fernet.generate_key()` 同一个形状:32 个随机字节的 urlsafe base64。 */
function generateFernetKey() {
  return crypto.randomBytes(32).toString("base64").replace(/\+/g, "-").replace(/\//g, "_");
}

function writePrivate(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temp = `${file}.tmp-${process.pid}`;
  fs.writeFileSync(temp, data, { mode: 0o600 });
  fs.renameSync(temp, file);
}

/** 壳令牌:HMAC-SHA256(主密钥, "mosael-shell-origin"),十六进制。和后端 core/shell_origin.shell_token 同一个算法。 */
function shellToken(key) {
  return crypto.createHmac("sha256", key).update("mosael-shell-origin").digest("hex");
}

/**
 * 取这个数据目录的主密钥。
 *
 * 回 `{ key, sealed }`:`sealed` 为真 = 密钥由钥匙串封存、要经标准输入交给后端;为假 = 钥匙串不可用,
 * 后端照旧读数据目录里的 `secret.key`(这里保证它已存在,好让壳和后端拿同一把算壳令牌)。
 *
 * @param {string} dataDir
 * @param {{ isEncryptionAvailable(): boolean, encryptString(s: string): Buffer, decryptString(b: Buffer): string }} safeStorage
 * @param {(error: Error) => void} [log] 封存失败这一笔写哪(启动那步把它接到 main.log)。
 * @returns {{ key: string, sealed: boolean }}
 */
function resolveMasterKey(dataDir, safeStorage, log = () => undefined) {
  const sealed = path.join(dataDir, SEALED_NAME);
  const plain = path.join(dataDir, PLAIN_NAME);
  if (fs.existsSync(sealed)) {
    let key;
    try {
      //: 钥匙串用不了(isEncryptionAvailable 为假)时 decryptString 同样抛错,一并算解不开 —— 封存过就不降级。
      key = safeStorage.decryptString(fs.readFileSync(sealed)).trim();
    } catch (error) {
      throw new SealedKeyUnavailableError(sealed, error);
    }
    //: 封存之后又出现了明文(比如从老版本的备份恢复):以封存的那把为准,明文只有一致时才删 ——
    //: 不一致说明它来自别的数据,留着让人看见,不替他删。
    if (fs.existsSync(plain) && fs.readFileSync(plain, "utf8").trim() === key) fs.rmSync(plain, { force: true });
    return { key, sealed: true };
  }
  const plainKey = () => {
    if (!fs.existsSync(plain)) writePrivate(plain, generateFernetKey());
    return { key: fs.readFileSync(plain, "utf8").trim(), sealed: false };
  };
  if (!safeStorage.isEncryptionAvailable()) return plainKey();
  const key = fs.existsSync(plain) ? fs.readFileSync(plain, "utf8").trim() : generateFernetKey();
  try {
    writePrivate(sealed, safeStorage.encryptString(key));
    //: 解得回同一把才删明文 —— 否则丢的是所有已存凭据。
    if (safeStorage.decryptString(fs.readFileSync(sealed)).trim() === key) {
      fs.rmSync(plain, { force: true });
      return { key, sealed: true };
    }
  } catch (error) {
    //: 第一次封存就出错:落到下面,明文是唯一的那一把。
    //: 这是安全相关的降级,得留一笔 —— 「我以为钥匙是封存的」不能靠猜。
    log(error instanceof Error ? error : new Error(String(error)));
  }
  fs.rmSync(sealed, { force: true });
  if (!fs.existsSync(plain)) writePrivate(plain, key);
  return plainKey();
}

/** 封存过的主密钥解不开。带着封存文件的路径,给人看的对话框里要说是哪一份。 */
class SealedKeyUnavailableError extends Error {
  constructor(sealedPath, cause) {
    super(`the sealed master key could not be unlocked: ${cause instanceof Error ? cause.message : String(cause)}`, { cause });
    this.name = "SealedKeyUnavailableError";
    this.sealedPath = sealedPath;
  }
}

/**
 * 取主密钥,取不到就问人,直到取到或者人说退出。退出回 null —— 调用方据此不起后端。
 *
 * `ask` 回 "retry"(再试一次)、"keychain"(先打开钥匙串访问再试)或 "quit"。
 * @param {{
 *   dataDir: string,
 *   safeStorage: Parameters<typeof resolveMasterKey>[1],
 *   ask: (error: Error) => Promise<"retry" | "keychain" | "quit">,
 *   openKeychain?: () => Promise<unknown> | void,
 *   log?: (error: Error) => void,
 * }} options
 * @returns {Promise<{ key: string, sealed: boolean } | null>}
 */
async function unlockMasterKey({ dataDir, safeStorage, ask, openKeychain = () => undefined, log = () => undefined }) {
  for (;;) {
    try {
      return resolveMasterKey(dataDir, safeStorage, log);
    } catch (error) {
      log(error);
      const choice = await ask(error);
      if (choice === "quit") return null;
      if (choice === "keychain") await openKeychain();
    }
  }
}

module.exports = {
  PLAIN_NAME,
  SEALED_NAME,
  SealedKeyUnavailableError,
  generateFernetKey,
  resolveMasterKey,
  shellToken,
  unlockMasterKey,
};
