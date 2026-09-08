import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import { KTX2Loader } from "three/addons/loaders/KTX2Loader.js";
import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";

import { DECODER_DIRS, DECODER_PREFIX } from "./decoderAssets";

/**
 * 会解压缩的 glTF 加载器。
 *
 * 此前用的是裸 `GLTFLoader`,于是压缩过的模型一律解不开 —— 文档只能写「请导出普通 GLB」。
 * 而**贴图正是体积的大头**:被迫导出未压缩的结果,是一个本来 20 MB 的场景变成 120 MB,
 * 然后撞上体积上限。接上解码器之后,同一个场景往往根本不会超。
 *
 * 三样各管一段:
 *
 *     KTX2 (basis)   贴图。压缩比最高的那一段,而且它在显存里也是压着的
 *     Draco          网格。Blender 导出面板上那个「压缩」勾的就是它
 *     meshopt        网格 + 动画,纯 JS,不需要额外资源文件
 *
 * 解码器文件由 vite.config.ts 的 `mosael:three-decoders` 摆到 `/three/` 下,**从装着的那个
 * three 里取**,升级 three 会自动跟上(wasm 和 loader 是配套的,版本对不上时的症状只是
 * 「某些模型解不开」,不会有人报错)。
 *
 * **一个应用只建一次**:DRACOLoader 和 KTX2Loader 各自带一池 worker,每次加载都新建
 * 就是每次都新开一批 worker,还都不回收。
 */
let shared: GLTFLoader | null = null;

/** 相对当前文档解析 —— 打包后的 Electron 用 `base: "./"` 走 file://,绝对路径在那里是错的。 */
const decoders = (dir: string) => new URL(`${DECODER_PREFIX}/${dir}/`, document.baseURI).href;

export function gltfLoader(renderer: THREE.WebGLRenderer): GLTFLoader {
  if (shared) return shared;
  const draco = new DRACOLoader().setDecoderPath(decoders(DECODER_DIRS.draco));
  // KTX2 要问渲染器支持哪些压缩格式(不同 GPU 能吃的不一样),所以建的时候要给它一个。
  const ktx2 = new KTX2Loader().setTranscoderPath(decoders(DECODER_DIRS.basis)).detectSupport(renderer);
  shared = new GLTFLoader()
    .setDRACOLoader(draco)
    .setKTX2Loader(ktx2)
    .setMeshoptDecoder(MeshoptDecoder);
  return shared;
}
