/**
 * sidecar 打包产物的冒烟:能不能真的构造出模型、能不能真的起一次授权登录。
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
 * 第二段(授权登录)是同一类故障的另一处:pi 的 OAuth 流程默认走动态 import,靠
 *   `import.meta.url.endsWith(".js")`
 * 判断运行形态 —— 而 CJS 产物里 import.meta 是 `{}`,于是点「授权登录」当场炸在
 *   TypeError: Cannot read properties of undefined (reading 'endsWith')
 * 解法是 registerBunOAuthFlows()(把各家流程静态注册进来)。这条同样只在打包后可见。
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
  void smokeAuthLogin();
}, 9000);

/**
 * 第二段:auth_login 能不能走过「加载授权流程」这一步。
 *
 * 判据同样是**失败的种类**:设备码要打真实网络,离线时拿不到,但那时的错误应该是网络类的,
 * 绝不该是加载类的。所以断言「没有加载期 TypeError」,并且确实看到了设备码/授权链接或一个
 * 网络错误 —— 而不是简单地断言某个字符串不出现(那样进程一启动就崩也算通过)。
 */
function smokeAuthLogin() {
  const child = spawn(process.execPath, [bundle], { stdio: ["pipe", "pipe", "pipe"] });
  let output = "";
  child.stdout.on("data", (d) => (output += d));
  child.stderr.on("data", (d) => (output += d));
  child.stdin.write(
    JSON.stringify({
      type: "auth_login",
      loginId: "smoke",
      piProvider: "kimi-coding",
      profileId: "p",
      // 凭据写回用不到(还没走到那一步),给个必然连不上的地址即可。
      apiBase: "http://127.0.0.1:9",
      token: "t",
    }) + "\n",
  );

  setTimeout(() => {
    child.kill();
    const loadFailure = /endsWith|is not a constructor|Dynamic require|Cannot find module|SyntaxError/i.test(output);
    const reachedFlow = /device_code|auth_url|verificationUri/i.test(output);
    const networkFailure = /ECONNREFUSED|fetch failed|ENOTFOUND|socket|timeout/i.test(output);

    if (loadFailure || !(reachedFlow || networkFailure)) {
      console.error("FAIL  授权流程没能加载起来:");
      console.error(`      走到流程=${reachedFlow} 网络失败=${networkFailure} 加载失败=${loadFailure}`);
      console.error(output.slice(0, 800));
      process.exit(1);
    }
    console.log(
      reachedFlow
        ? "PASS  打包产物能起一次设备码授权(拿到了设备码)"
        : "PASS  打包产物的授权流程已加载(本次离线,失败在网络上)",
    );
    process.exit(0);
  }, 12000);
}
