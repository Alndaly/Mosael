const { createHash, randomBytes } = require("node:crypto");
const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { GenericProvider } = require("electron-updater/out/providers/GenericProvider");
const { MacUpdater } = require("electron-updater/out/MacUpdater");
const { DownloadedUpdateHelper } = require("electron-updater/out/DownloadedUpdateHelper");
const { ElectronHttpExecutor } = require("electron-updater/out/electronHttpExecutor");

const { createRequire } = require("node:module");
const { archive } = createRequire(require.resolve("electron-builder/package.json"))("app-builder-lib/out/targets/archive.js");
const { app } = require("electron");
const { CancellationToken } = createRequire(require.resolve("electron-updater/package.json"))("builder-util-runtime");
const root = fs.mkdtempSync(path.join(os.tmpdir(), "mosael-differential-"));
const repo = process.cwd();
const BASE_APP = randomBytes(2 * 1024 * 1024);
const BASE_FRAMEWORK = randomBytes(1024 * 1024);
const oldVersion = "1.0.0";
const newVersion = "2.0.0";

async function makeArtifact(version, changed) {
  const dir = path.join(root, `app-${version}`);
  fs.mkdirSync(dir, { recursive: true });
  const body = Buffer.from(BASE_APP);
  if (changed) randomBytes(8192).copy(body, 1024 * 1024);
  fs.writeFileSync(path.join(dir, "app.bundle"), body);
  fs.writeFileSync(path.join(dir, "framework.bin"), BASE_FRAMEWORK);
  fs.writeFileSync(path.join(dir, "README.md"), `Mosael ${version}\n`);
  const zip = path.join(root, `Mosael-${version}-mac-signed.zip`);
  await archive("zip", zip, dir, { compression: "normal", storedPaths: ["app.bundle"], preserveSymlinks: true });
  return zip;
}

function writeMetadata(version, file) {
  execFileSync(process.execPath, [
    path.join(repo, "scripts", "write-update-metadata.mjs"),
    "--version", version,
    "--mac", file,
    "--out", root,
  ], { cwd: repo, env: { ...process.env, ELECTRON_RUN_AS_NODE: "1" }, stdio: "pipe" });
}

async function main() {
  const oldZip = await makeArtifact(oldVersion, false);
  const newZip = await makeArtifact(newVersion, true);
  writeMetadata(oldVersion, oldZip);
  writeMetadata(newVersion, newZip);

  const requests = [];
  const server = http.createServer((req, res) => {
    const pathname = decodeURIComponent((req.url || "/").split("?")[0]);
    const file = path.join(root, pathname);
    if (!fs.existsSync(file)) {
      res.writeHead(404).end();
      return;
    }
    const data = fs.readFileSync(file);
    let body = data;
    let status = 200;
    const range = req.headers.range;
    if (range) {
      const match = /^bytes=(\d+)-(\d*)$/.exec(range);
      if (!match) {
        res.writeHead(400).end();
        return;
      }
      const start = Number(match[1]);
      const end = match[2] ? Math.min(Number(match[2]), data.length - 1) : data.length - 1;
      body = data.subarray(start, end + 1);
      status = 206;
      res.setHeader("Content-Range", `bytes ${start}-${end}/${data.length}`);
    }
    requests.push({ pathname, range: range || "", status, bytes: req.method === "HEAD" ? 0 : body.length });
    res.writeHead(status, { "Content-Length": body.length, "Accept-Ranges": "bytes" });
    res.end(req.method === "HEAD" ? undefined : body);
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const baseUrl = `http://127.0.0.1:${server.address().port}/`;
  const executor = new ElectronHttpExecutor();
  const provider = new GenericProvider({ url: baseUrl }, { channel: null, isAddNoCacheQuery: false }, {
    executor,
    isUseMultipleRangeRequest: false,
  });
  const sha512 = createHash("sha512").update(fs.readFileSync(newZip)).digest("base64");
  const updateInfo = {
    version: newVersion,
    path: path.basename(newZip),
    sha512,
    files: [{ url: path.basename(newZip), sha512, size: fs.statSync(newZip).size }],
  };
  const [fileInfo] = provider.resolveFiles(updateInfo);
  const updater = new MacUpdater(null, { version: oldVersion });
  updater.httpExecutor = executor;
  const cacheDir = path.join(root, "cache");
  fs.mkdirSync(cacheDir, { recursive: true });
  fs.copyFileSync(oldZip, path.join(cacheDir, "update.zip"));
  updater.downloadedUpdateHelper = new DownloadedUpdateHelper(cacheDir);
  const destination = path.join(root, "downloaded.zip");
  try {
    const fallbackToFull = await updater.differentialDownloadInstaller(fileInfo, {
      updateInfoAndProvider: { provider, info: updateInfo },
      requestHeaders: null,
      disableDifferentialDownload: false,
      cancellationToken: new CancellationToken(),
    }, destination, provider, "update.zip");
    const downloadedSha = createHash("sha512").update(fs.readFileSync(destination)).digest("base64");
    const zipRequests = requests.filter((one) => one.pathname.endsWith(".zip"));
    const downloadedBytes = zipRequests.reduce((sum, one) => sum + one.bytes, 0);
    const result = {
      differential: fallbackToFull === false,
      checksumMatches: downloadedSha === sha512,
      fullBytes: fs.statSync(newZip).size,
      downloadedBytes,
      rangeRequests: zipRequests.filter((one) => one.range).length,
      requests: zipRequests,
    };
    console.log(JSON.stringify(result, null, 2));
    if (fallbackToFull !== false) throw new Error("updater fell back to a full download");
    if (downloadedSha !== sha512) throw new Error("differential result checksum mismatch");
    if (downloadedBytes >= fs.statSync(newZip).size) throw new Error("differential download did not save bytes");
    if (!zipRequests.some((one) => one.range)) throw new Error("no Range request was made");
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

app.whenReady().then(main).catch((error) => {
  console.error(error);
  process.exitCode = 1;
}).finally(() => {
  fs.rmSync(root, { recursive: true, force: true });
  setTimeout(() => process.exit(process.exitCode || 0), 20);
});
