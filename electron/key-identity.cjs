"use strict";

/**
 * 一个数据目录的主密钥归哪个系统钥匙串身份。
 *
 * `safeStorage` 在 macOS 按应用名选钥匙串项，所以「应用名」不能再由开发版/打包版简单决定：
 * 默认 `~/.mosael` 是打包版的生产数据，必须继续用 `Mosael`；临时/开发数据（如 `~/.mosael-dev`）
 * 用 `Mosael Dev`。已有封存钥匙的数据目录以 `secret.key.owner` 为准；旧版没有这个文件时，
 * 有 sealed 就说明它由打包版封存，按 `Mosael` 处理。
 *
 * 这样换一个可执行文件打开同一个数据目录，仍能找到同一把钥匙，而不是悄悄换成另一把。
 */
const fs = require("node:fs");
const path = require("node:path");

const OWNER_NAME = "secret.key.owner";
const SEALED_NAME = "secret.key.sealed";

function validName(value) {
  return /^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$/.test(value);
}

function keychainName(dataDir, { dev = false } = {}) {
  const dir = path.resolve(dataDir);
  try {
    const owner = fs.readFileSync(path.join(dir, OWNER_NAME), "utf8").trim();
    if (validName(owner)) return owner;
  } catch {
    // 还没有归属文件：按下面的旧数据 / 默认规则推断。
  }
  if (fs.existsSync(path.join(dir, SEALED_NAME))) return "Mosael";
  return dev ? "Mosael Dev" : "Mosael";
}

function rememberKeychainName(dataDir, name) {
  if (!validName(name)) throw new Error(`invalid keychain identity: ${name}`);
  const file = path.join(path.resolve(dataDir), OWNER_NAME);
  if (fs.existsSync(file) && fs.readFileSync(file, "utf8").trim() === name) return;
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, `${name}\n`, { mode: 0o600 });
}

module.exports = { OWNER_NAME, keychainName, rememberKeychainName };
