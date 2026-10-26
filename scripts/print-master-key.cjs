// 把桌面版封存的主密钥解出来打到 stdout —— 只给**本机开发**用。
//
// 背景:桌面版会把 `<数据目录>/secret.key` 封存进系统钥匙串(`safeStorage`),删掉明文;之后
// 直接对着同一个数据目录跑后端(`pnpm dev` 的 dev:backend 就是这么起的)就拿不到钥匙,后端会
// 拒绝启动(它不肯另生一把,那会把已存的凭据全废掉)。这个脚本用 Electron 的 safeStorage 解开它,
// 让 dev 后端可以 `MOSAEL_SECRET_KEY=$(...)` 拿到同一把。
//
// 用法(不需要开窗口):
//     ./node_modules/.bin/electron --no-sandbox scripts/print-master-key.cjs
// 解不开时打印空行并以 1 退出 —— 调用方按「没有拿到」处理。
const fs = require("node:fs");
const path = require("node:path");

const { app, safeStorage } = require("electron");
const { keychainName } = require("../electron/key-identity.cjs");

const dataDir = process.env.MOSAEL_DATA_DIR
  ? path.resolve(process.env.MOSAEL_DATA_DIR)
  : path.join(process.env.HOME || "", ".mosael");

//: safeStorage 在 macOS 按应用名找系统钥匙串项。名字属于数据目录 —— 与主进程读同一份归属规则,
//: 否则默认 `~/.mosael` 会拿 Mosael Dev 去解打包版封存的钥匙,必然失败。
app.setName(keychainName(dataDir, { dev: true }));

const sealed = path.join(dataDir, "secret.key.sealed");
const plain = path.join(dataDir, "secret.key");

app.whenReady().then(() => {
  try {
    if (fs.existsSync(plain)) {
      process.stdout.write(fs.readFileSync(plain, "utf8").trim());
      app.exit(0);
      return;
    }
    if (!fs.existsSync(sealed) || !safeStorage.isEncryptionAvailable()) {
      app.exit(1);
      return;
    }
    process.stdout.write(safeStorage.decryptString(fs.readFileSync(sealed)).trim());
    app.exit(0);
  } catch (error) {
    console.error(`[print-master-key] ${error.message}`);
    app.exit(1);
  }
});
