/**
 * 等用户处理掉一张卡 —— 这次 turn 就停在那里。选择卡是新接上去的,确认卡是回归护栏。
 *
 * 问了就等在那儿 —— 选择卡的答案要作为**工具结果**回到它被问的那个位置。
 *
 * 此前 ask_user 立刻返回 {question_id, status: pending},这一轮随即结束;用户作答后只能靠
 * 往对话里补一条「我选好了:…」把模型重新叫醒 —— 而那条消息用户没写过、会话正忙时还会躺进
 * 输入框上方的队列条里(真机上撞到的样子)。确认卡走的一直是阻塞那条路,选择卡只是没接上去。
 *
 * 三条判据:
 *   · 答了 → 工具结果里就是答案,不是 question_id;
 *   · 跳过 → skipped，模型该按自己的判断继续;
 *   · 到点还没答 → **不抛错**。超时只说明用户还没顾上,答案仍然会由回执送到;抛错会让模型
 *     以为问这件事失败了,转头把同一张卡再立一遍,而第一张还在用户面前。
 *
 * 跑法:node agent-sidecar/test/await-user-cards.test.mjs
 */
import assert from "node:assert/strict";
import http from "node:http";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, "..");

/** 与 proxy.test.mjs 同一个理由用 esbuild 的 JS API:.bin 垫片在 Windows 上起不来。 */
async function bundle(entry, outfile) {
  const esbuild = await import("esbuild");
  await esbuild.build({
    entryPoints: [entry],
    bundle: true,
    platform: "node",
    format: "esm",
    external: ["@earendil-works/pi-agent-core"],
    outfile,
  });
  return pathToFileURL(outfile).href;
}

const MANIFEST = [
  { name: "ask_user", description: "问", parameters: { type: "object", properties: {} }, awaits_answer: true },
  //: 确认卡那半是**回归护栏**:两条等待路径共用一个循环,而它们的超时结局相反。
  { name: "render_sequence", description: "导", parameters: { type: "object", properties: {} }, confirmation: true },
];

/** 假后端。`plan` 决定第 n 次查卡返回什么状态。 */
function startBackend(plan) {
  let polls = 0;
  const server = http.createServer((req, res) => {
    const json = (body) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(body));
    };
    if (req.url === "/api/agent/tools") return json(MANIFEST);
    if (req.url === "/api/agent/tools/ask_user") {
      req.resume();
      return json({ result: { question_id: "q1", status: "pending" } });
    }
    if (req.url === "/api/agent/tools/render_sequence") {
      req.resume();
      return json({ result: { confirmation_id: "c1", status: "pending" } });
    }
    if (req.url === "/api/confirmations/c1") {
      const state = plan[Math.min(polls, plan.length - 1)];
      polls += 1;
      return json({ id: "c1", ...state });
    }
    if (req.url === "/api/agent/questions/q1") {
      const state = plan[Math.min(polls, plan.length - 1)];
      polls += 1;
      return json({ id: "q1", ...state });
    }
    res.writeHead(404);
    res.end("{}");
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () =>
      resolve({ server, polls: () => polls, base: `http://127.0.0.1:${server.address().port}` }),
    );
  });
}

const out = await bundle(path.join(root, "src", "tools.ts"), path.join(root, "dist", "tools.test-bundle.mjs"));

async function callTool(name, plan, waitMs) {
  process.env.MOSAEL_CARD_WAIT_MS = String(waitMs);
  const backend = await startBackend(plan);
  const { buildAllTools } = await import(`${out}?case=${Math.random()}`);
  const tools = await buildAllTools(backend.base, "t", "w1");
  const tool = tools.find((one) => one.name === name);
  assert.ok(tool, `manifest 里的 ${name} 没有长成工具`);
  try {
    const result = await tool.execute("call-1", {});
    return { result, polls: backend.polls() };
  } finally {
    backend.server.close();
  }
}

const askUserResult = (plan, waitMs) => callTool("ask_user", plan, waitMs);

// 1) 用户答了 → 答案就是工具结果,而且**等到了**才返回(不是第一次查就交差)
{
  const { result, polls } = await askUserResult(
    [{ status: "pending", answers: null }, { status: "answered", answers: { "走哪条": ["英文"] } }],
    5_000,
  );
  assert.ok(polls >= 2, `没等 —— 只查了 ${polls} 次就返回了`);
  assert.equal(result.details.data.status, "answered");
  assert.deepEqual(result.details.data.answers, { "走哪条": ["英文"] });
  // question_id 不该出现在**模型看到的东西**里:它是"去轮询"那条协议的残留,模型拿它做不了
  // 任何事。`content` 才是模型读的那一份 —— 此前这条断言打的是 `details.data`,而那时
  // `jsonResult` 让两份完全相同,所以断哪一份都一样。
  assert.ok(!JSON.stringify(result.content).includes("q1"), "模型看到的结果里还留着 question_id");
  // 而**界面需要它**:同一次作答会留下两份痕迹(这条工具结果、和后端送回会话的回执),
  // 阻塞这条路上两份都在,界面靠这个 id 认出它们说的是同一件事,只画一遍。超时那条路上
  // 工具结果是 pending、回执是唯一记录 —— 所以猜不得,必须有钥匙。
  assert.equal(result.details.data.question_id, "q1", "界面拿不到卡片身份,去重只能靠猜");
}

// 2) 用户跳过 → 说清是跳过,模型按自己的判断继续
{
  const { result } = await askUserResult([{ status: "dismissed", answers: null }], 5_000);
  assert.equal(result.details.data.status, "dismissed");
  assert.equal(result.details.data.skipped, true);
}

// 3) 到点还没答 → 不抛错,如实说"还没答"
{
  const { result } = await askUserResult([{ status: "pending", answers: null }], 120);
  assert.equal(result.details.data.status, "pending", "超时给的不是 pending");
  assert.ok(
    String(result.details.data.message).includes("不要再问一遍"),
    `超时那句话得拦住"再问一遍":${result.details.data.message}`,
  );
}

// 4) 确认卡那条没被这次重构改掉:等到执行完,拿到的是结果本身
{
  const { result, polls } = await callTool(
    "render_sequence",
    [{ status: "pending", result: null }, { status: "executed", result: { job_id: "j1" } }],
    5_000,
  );
  assert.ok(polls >= 2, `确认卡没等 —— 只查了 ${polls} 次`);
  assert.deepEqual(result.details.data, { job_id: "j1" });
}

// 5) 确认卡超时**要**抛错 —— 和选择卡相反:那个动作没有发生,说成别的会让模型以为它做过了
{
  await assert.rejects(
    () => callTool("render_sequence", [{ status: "pending", result: null }], 120),
    /超时/,
    "确认卡超时被说成了别的",
  );
}

console.log("await-user-cards: ok");
