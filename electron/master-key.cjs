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
 * @returns {{ key: string, sealed: boolean }}
 */
function resolveMasterKey(dataDir, safeStorage) {
  if (!safeStorage.isEncryptionAvailable()) {
    const plain = path.join(dataDir, PLAIN_NAME);
    if (!fs.existsSync(plain)) writePrivate(plain, generateFernetKey());
    return { key: fs.readFileSync(plain, "utf8").trim(), sealed: false };
  }
  const sealed = path.join(dataDir, SEALED_NAME);
  const plain = path.join(dataDir, PLAIN_NAME);
  if (fs.existsSync(sealed)) {
    const key = safeStorage.decryptString(fs.readFileSync(sealed)).trim();
    //: 封存之后又出现了明文(比如从老版本的备份恢复):以封存的那把为准,明文只有一致时才删 ——
    //: 不一致说明它来自别的数据,留着让人看见,不替他删。
    if (fs.existsSync(plain) && fs.readFileSync(plain, "utf8").trim() === key) fs.rmSync(plain, { force: true });
    return { key, sealed: true };
  }
  const key = fs.existsSync(plain) ? fs.readFileSync(plain, "utf8").trim() : generateFernetKey();
  writePrivate(sealed, safeStorage.encryptString(key));
  //: 解得回同一把才删明文 —— 否则丢的是所有已存凭据。
  if (safeStorage.decryptString(fs.readFileSync(sealed)).trim() !== key) {
    fs.rmSync(sealed, { force: true });
    if (!fs.existsSync(plain)) writePrivate(plain, key);
    return { key, sealed: false };
  }
  fs.rmSync(plain, { force: true });
  return { key, sealed: true };
}

module.exports = { PLAIN_NAME, SEALED_NAME, generateFernetKey, resolveMasterKey, shellToken };
