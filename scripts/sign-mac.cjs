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

async function signMac(options) {
  const { signAsync } = require("@electron/osx-sign");
  const ignored = options.ignore == null ? [] : [options.ignore].flat();
  const ignore = (file) => ignored.some((rule) =>
    typeof rule === "function" ? rule(file) : Boolean(file.match(rule))) || !needsCodeSignature(file);
  for (let attempt = 0; ; attempt++) {
    try {
      return await signAsync({ ...options, ignore });
    } catch (error) {
      if (attempt >= 2 || !String(error).includes("timestamp service is not available")) throw error;
      await new Promise((resolve) => setTimeout(resolve, 5000 * (attempt + 1)));
    }
  }
}

module.exports = signMac;
module.exports.needsCodeSignature = needsCodeSignature;
