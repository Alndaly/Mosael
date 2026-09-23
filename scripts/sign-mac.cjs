const fs = require("node:fs");

const MACH_O_MAGIC = new Set([
  0xfeedface, 0xcefaedfe, 0xfeedfacf, 0xcffaedfe,
  0xcafebabe, 0xbebafeca, 0xcafebabf, 0xbfbafeca,
]);

/** Resource files are sealed by their containing bundle; only native code needs codesign. */
function needsCodeSignature(file) {
  if (fs.statSync(file).isDirectory()) return true;
  const handle = fs.openSync(file, "r");
  try {
    const magic = Buffer.alloc(4);
    return fs.readSync(handle, magic, 0, 4, 0) === 4 && MACH_O_MAGIC.has(magic.readUInt32BE());
  } finally {
    fs.closeSync(handle);
  }
}

/** 会自己好的那几种签名失败 —— 重试有意义,其余的立刻抛。
 *
 * **两种都不是我们做错了什么,而是签名开始得太早。** 打包刚把 600MB 的包铺完,第一次
 * codesign 就可能撞上还没落定的状态:codesign 自己说的是「internal error in Code Signing
 * subsystem」,electron-builder 转出来的是「Operation not permitted」——同一件事的两层措辞,
 * 所以两条都要认。实测症状很有迷惑性:**每次都停在它遍历到的第一个二进制上**(那恰好是
 * 一个 11MB 的 .so),看着像那个文件坏了;而手动对同一个文件签、24 个并发签、包内包外签、
 * 全新拷贝签,全部成功。在第一次调用前等 20 秒,整个构建一次过。
 *
 * 时间戳那条是另一个来源:`timestamp.apple.com` 偶发不可用。
 *
 * 认得宽一点是划算的:真的权限问题重试三次仍然失败,只多花十几秒;而认得窄会让一次本该
 * 成功的发布构建整个红掉 —— 这两边的代价差着量级。
 */
function isTransientSigningFailure(error) {
  const text = String(error);
  return text.includes("timestamp service is not available")
    || text.includes("internal error in Code Signing subsystem")
    || text.includes("Operation not permitted");
}

/** 重试循环本身。`sign` 由调用方给 —— 生产里是 @electron/osx-sign 的 `sign`,测试里是一个假的。 */
async function signWith(sign, options) {
  const ignored = options.ignore == null ? [] : [options.ignore].flat();
  const ignore = (file) => ignored.some((rule) =>
    typeof rule === "function" ? rule(file) : Boolean(file.match(rule))) || !needsCodeSignature(file);
  for (let attempt = 0; ; attempt++) {
    try {
      return await sign({ ...options, ignore });
    } catch (error) {
      if (attempt >= 2 || !isTransientSigningFailure(error)) throw error;
      // **重试要出声。** 静默重试等于把「这次构建其实撞了一下」藏起来 —— 下次它变成必现的
      // 时候,日志里一点线索都没有,又得从头查一遍那个「看起来坏掉的 .so」。
      console.warn(`[sign-mac] 第 ${attempt + 1} 次签名失败,${5 * (attempt + 1)} 秒后重试:`
        + ` ${String(error).split("\n").find((line) => line.trim()) || error}`);
      await new Promise((resolve) => setTimeout(resolve, 5000 * (attempt + 1)));
    }
  }
}

/** electron-builder 的 `mac.sign` 钩子。osx-sign 2.x 只发 ESM,入口叫 `sign`(1.x 是 `signAsync`)。 */
async function signMac(options) {
  const { sign } = await import("@electron/osx-sign");
  return signWith(sign, options);
}

module.exports = signMac;
module.exports.signWith = signWith;
module.exports.needsCodeSignature = needsCodeSignature;
module.exports.isTransientSigningFailure = isTransientSigningFailure;
