/**
 * KTX2 / Draco 解码器资源的落点。**vite.config.ts 和加载器共用这一份。**
 *
 * 分两处写的话,改了目录名或漏带一个文件,症状只是"某些压缩模型解不开" —— 没有任何地方会
 * 报"配置对不上",而报错(three 抛的一句 no DRACOLoader / failed to load transcoder)离
 * 真正改错的那一行已经隔了很远。
 *
 * 路径相对 `three` 包里的 `examples/jsm/libs`,同时也是它们在产物里的相对落点(带 PREFIX)。
 */
export const DECODER_PREFIX = "three";

/** 只带 glTF 用得上的那份 draco —— 完整版体积翻倍,而我们只解 glTF 里的网格。 */
export const DECODER_DIRS = { basis: "basis", draco: "draco/gltf" } as const;

export const DECODER_FILES = [
  `${DECODER_DIRS.basis}/basis_transcoder.js`,
  `${DECODER_DIRS.basis}/basis_transcoder.wasm`,
  `${DECODER_DIRS.draco}/draco_decoder.js`,
  `${DECODER_DIRS.draco}/draco_decoder.wasm`,
  `${DECODER_DIRS.draco}/draco_wasm_wrapper.js`,
] as const;
