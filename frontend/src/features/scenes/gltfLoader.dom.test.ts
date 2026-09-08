/** @vitest-environment jsdom */
/**
 * 钉的是**接线**:三个解码器都挂上了、而且整个应用只建一次。
 *
 * 这段最容易被悄悄退回去 —— `new GLTFLoader()` 看起来完全正常,只是压缩过的模型解不开,
 * 而那时的报错是 three 抛的一句「no DRACOLoader instance provided」,离"文档说请导出普通 GLB"
 * 那个决定已经隔了很远。
 */
import { afterEach, expect, it, vi } from "vitest";

import { DECODER_FILES, DECODER_PREFIX } from "./decoderAssets";
import { gltfLoader } from "./gltfLoader";

/** detectSupport 只问渲染器"你能吃哪些压缩格式",给它一个够用的假的。 */
function renderer() {
  return {
    extensions: { has: () => false },
    capabilities: { isWebGL2: true },
    getContext: () => ({}),
  } as never;
}

afterEach(() => vi.restoreAllMocks());

it("三个解码器都挂上了", () => {
  const loader = gltfLoader(renderer()) as unknown as {
    dracoLoader: { decoderPath: string } | null;
    ktx2Loader: { transcoderPath: string } | null;
    meshoptDecoder: unknown;
  };
  expect(loader.dracoLoader, "Draco 没挂上 —— Blender 导出面板上那个「压缩」勾了就解不开").toBeTruthy();
  expect(loader.ktx2Loader, "KTX2 没挂上 —— 贴图是体积的大头,不解它就只能导出未压缩的").toBeTruthy();
  expect(loader.meshoptDecoder, "meshopt 没挂上").toBeTruthy();
});

it("解码器路径相对文档解析,不是绝对路径", () => {
  // 打包后的 Electron 用 base:"./" 走 file://,`/three/...` 那种绝对路径在那里指向磁盘根。
  // DRACOLoader 在 setDecoderPath 时就把三个文件名拼好存进 decoderPaths,所以这里能直接核对
  // 最终地址 —— 少一个斜杠、放错子目录,都在这一步就看得出来。
  const loader = gltfLoader(renderer()) as unknown as {
    dracoLoader: { decoderPaths: { js: string; wasm: string; dep_js: string } };
    ktx2Loader: { transcoderPath: string };
  };
  const root = document.baseURI.replace(/[^/]*$/, "");
  const { js, wasm, dep_js } = loader.dracoLoader.decoderPaths;
  expect(wasm).toBe(`${root}three/draco/gltf/draco_decoder.wasm`);
  expect(js).toBe(`${root}three/draco/gltf/draco_wasm_wrapper.js`);
  expect(dep_js).toBe(`${root}three/draco/gltf/draco_decoder.js`);
  // KTX2 拼文件名的时机在加载时,这里只核目录 —— 末尾那个斜杠不能少。
  expect(loader.ktx2Loader.transcoderPath).toBe(`${root}three/basis/`);
});

it("只建一次 —— 两个 loader 就是两池 worker,而且都不回收", () => {
  expect(gltfLoader(renderer())).toBe(gltfLoader(renderer()));
});

it("加载器要的文件,清单里都有", () => {
  // vite.config.ts 按 DECODER_FILES 落盘,加载器按 DECODER_DIRS 拼地址 —— 两边同源。
  // 这条守的是"拼出来的文件名不在清单里":那样产物里就没有它,而症状只是模型解不开。
  const loader = gltfLoader(renderer()) as unknown as {
    dracoLoader: { decoderPaths: Record<string, string> };
    ktx2Loader: { transcoderPath: string };
  };
  const shipped = new Set(DECODER_FILES.map((file) => `${DECODER_PREFIX}/${file}`));
  const root = document.baseURI.replace(/[^/]*$/, "");
  const wanted = [
    ...Object.values(loader.dracoLoader.decoderPaths),
    // KTX2Loader 加载时才拼这两个名字(见 three 的 KTX2Loader.init)。
    `${loader.ktx2Loader.transcoderPath}basis_transcoder.js`,
    `${loader.ktx2Loader.transcoderPath}basis_transcoder.wasm`,
  ];
  for (const url of wanted) expect(shipped, `${url} 不在 DECODER_FILES 里`).toContain(url.slice(root.length));
});
