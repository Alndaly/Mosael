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
 * - 系统没有可用的钥匙串(`isEncryptionAvailable()` 为假,常见于没有桌面密钥环的 Linux):什么都不动,
 *   后端照旧用数据目录里的 `secret.key`。那是如实的降级,不假装加了密。
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

/**
 * 取这个数据目录的主密钥;可用钥匙串时保证它以封存的形态落盘。回 `null` = 钥匙串不可用,交给后端自己取。
 *
 * @param {string} dataDir
 * @param {{ isEncryptionAvailable(): boolean, encryptString(s: string): Buffer, decryptString(b: Buffer): string }} safeStorage
 * @returns {string | null}
 */
function resolveMasterKey(dataDir, safeStorage) {
  if (!safeStorage.isEncryptionAvailable()) return null;
  const sealed = path.join(dataDir, SEALED_NAME);
  const plain = path.join(dataDir, PLAIN_NAME);
  if (fs.existsSync(sealed)) {
    const key = safeStorage.decryptString(fs.readFileSync(sealed)).trim();
    //: 封存之后又出现了明文(比如从老版本的备份恢复):以封存的那把为准,明文只有一致时才删 ——
    //: 不一致说明它来自别的数据,留着让人看见,不替他删。
    if (fs.existsSync(plain) && fs.readFileSync(plain, "utf8").trim() === key) fs.rmSync(plain, { force: true });
    return key;
  }
  const key = fs.existsSync(plain) ? fs.readFileSync(plain, "utf8").trim() : generateFernetKey();
  writePrivate(sealed, safeStorage.encryptString(key));
  //: 解得回同一把才删明文 —— 否则丢的是所有已存凭据。
  if (safeStorage.decryptString(fs.readFileSync(sealed)).trim() !== key) {
    fs.rmSync(sealed, { force: true });
    return null;
  }
  fs.rmSync(plain, { force: true });
  return key;
}

module.exports = { PLAIN_NAME, SEALED_NAME, generateFernetKey, resolveMasterKey };
