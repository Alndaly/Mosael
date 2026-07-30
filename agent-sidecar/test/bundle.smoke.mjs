/**
 * sidecar 打包产物的冒烟:能不能真的构造出模型。
 *
 * 为什么需要它:这类故障**只在 bundle 之后出现**,源码和类型都是对的,单元测试也照样绿。
 * 真实事故是 pi-ai 0.82 重排模块之后,esbuild 的 CJS 惰性初始化转换把 createModels 提到顶层、
 * 却把它引用的 ModelsImpl 留在 init_models 块里,而全包唯一一处 init_models() 又在
 * openai-completions 块内部 —— 于是每一轮对话都直接报
 *   TypeError: ModelsImpl is not a constructor
 * 用户侧表现为「智能体执行失败」,而 CI 一片绿。改成 ESM 打包后消失(ESM 的求值顺序是确定的)。
 *
 * 判据是**失败的种类**而不是成败:base_url 指向一个必然连不上的端口,所以这一轮一定失败;
 * 我们要的是它失败在网络上,而不是失败在构造器上。
 *
 * 跑法:node agent-sidecar/test/bundle.smoke.mjs
 */
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const bundle = path.join(here, "..", "dist", "sidecar.cjs");

const child = spawn(process.execPath, [bundle], { stdio: ["pipe", "pipe", "pipe"] });
let output = "";
child.stdout.on("data", (d) => (output += d));
child.stderr.on("data", (d) => (output += d));

child.stdin.write(
  JSON.stringify({
    type: "run_turn",
    turnId: "smoke",
    prompt: "hi",
    systemPrompt: "smoke test",
    // 9 号端口(discard)必然连不上 —— 我们要的就是它失败,只是不能失败在构造器上。
    provider: { baseUrl: "http://127.0.0.1:9/v1", apiKey: "k" },
    model: "smoke-model",
    apiBase: "http://127.0.0.1:9",
    token: "t",
    workspaceId: "w",
    sessionId: "s",
  }) + "\n",
);

setTimeout(() => {
  child.kill();

  // **要正面证据**,不能只检查某个错误字符串不出现 —— 那样进程一启动就崩也算"通过"。
  // 我第一次就是这么骗过自己的:把 CJS 产物写成 .mjs,它在加载期就炸了,输出里当然没有
  // "is not a constructor",于是假阳性通过。
  //
  // 正面证据 = sidecar 完整走到了「发起网络请求」这一步:它必须回一个 error 帧,且原因是
  // 连不上(ECONNREFUSED / fetch failed 之类),而不是加载或构造出的问题。
  const sawErrorFrame = /"type":"error"/.test(output);
  const reachedNetwork = /ECONNREFUSED|fetch failed|connect|ENOTFOUND|socket/i.test(output);
  const loadFailure = /is not a constructor|Dynamic require|Cannot find module|SyntaxError/i.test(output);

  if (loadFailure || !sawErrorFrame || !reachedNetwork) {
    console.error("FAIL  打包产物没能走到发起请求这一步:");
    console.error(`      error 帧=${sawErrorFrame} 触网=${reachedNetwork} 加载/构造失败=${loadFailure}`);
    console.error(output.slice(0, 800));
    process.exit(1);
  }
  console.log("PASS  打包产物完整跑到发起请求(失败原因是连不上,符合预期)");
  process.exit(0);
}, 9000);
