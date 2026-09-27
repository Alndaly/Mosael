import assert from "node:assert/strict";
import test from "node:test";

import "./support/alias.mjs";

const { SessionClient, REFRESH_LEEWAY_MS, RETRY_DELAY_MS } = await import("../src/lib/community/session.ts");
const { CommunityError } = await import("../src/lib/community/errors.ts");

const BASE = "/api/community/v1";
const USER = { id: "u1", handle: "kinda", display_name: "Kinda", avatar_url: null, role: "user" };

/** 假时钟 + 定时器:advance 时按到期顺序触发。 */
function fakeClock(start = 1_000_000) {
  let now = start;
  let seq = 0;
  const timers = new Map();
  return {
    now: () => now,
    setTimer(callback, ms) {
      const id = ++seq;
      timers.set(id, { at: now + ms, callback });
      return id;
    },
    clearTimer(id) {
      timers.delete(id);
    },
    /** 时钟跳过去而定时器不触发 —— 模拟标签页休眠。 */
    jump(ms) {
      now += ms;
    },
    pending: () => [...timers.values()].map((timer) => timer.at - now).sort((a, b) => a - b),
    async advance(ms) {
      const target = now + ms;
      for (;;) {
        const due = [...timers.entries()].filter(([, timer]) => timer.at <= target).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        timers.delete(due[0]);
        now = due[1].at;
        due[1].callback();
        await flush();
      }
      now = target;
    },
  };
}

/** 让排着的 promise、setImmediate(广播消息的投递、Response.json 的读流)都走完。 */
const flush = async () => {
  for (let i = 0; i < 20; i += 1) await new Promise((resolve) => setImmediate(resolve));
};

/** 一对相连的广播通道(同源的两个标签页)。发出的消息异步到达对方,和 BroadcastChannel 一样不回给自己。 */
function channelHub() {
  const members = [];
  const sent = [];
  return {
    sent,
    join() {
      const listeners = [];
      const member = {
        postMessage(message) {
          sent.push(message);
          for (const other of members) if (other !== member) setImmediate(() => other.listeners.forEach((fn) => fn({ data: structuredClone(message) })));
        },
        addEventListener(_type, fn) {
          listeners.push(fn);
        },
        close() {},
        listeners,
      };
      members.push(member);
      return member;
    },
  };
}

function hintStore(initial = false) {
  let on = initial;
  return { get: () => on, set: (value) => (on = value) };
}

const json = (status, body) =>
  new Response(body === undefined ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const loginBody = (token, expiresIn = 900) => ({ access_token: token, expires_in: expiresIn, user: USER });

/**
 * 一个假的社区服务:`routes[path](init)` 回 Response。记下每一次调用,refresh 另计数。
 * 受保护的接口只认 `valid` 里的令牌。
 */
function fakeServer({ refresh, protectedPaths = ["/me"], valid = new Set() } = {}) {
  const calls = [];
  const server = {
    calls,
    valid,
    refreshCount: 0,
    refreshGate: null,
    async fetch(url, init = {}) {
      const path = url.slice(BASE.length);
      const headers = new Headers(init.headers);
      calls.push({ path, method: init.method ?? "GET", auth: headers.get("Authorization"), headers, init });
      if (path === "/auth/refresh") {
        server.refreshCount += 1;
        if (server.refreshGate) await server.refreshGate;
        return refresh(server.refreshCount, headers);
      }
      if (path === "/auth/logout") return new Response(null, { status: 204 });
      if (protectedPaths.includes(path)) {
        const token = headers.get("Authorization")?.replace("Bearer ", "");
        if (!token || !server.valid.has(token)) return json(401, { error: { code: "token_expired", message: "expired" } });
        return json(200, { ok: true, token });
      }
      return json(404, { error: { code: "not_found", message: "nope" } });
    },
  };
  return server;
}

function makeClient({ server, clock = fakeClock(), channel = null, hint = hintStore(true), random = () => 0 }) {
  const client = new SessionClient({
    baseUrl: BASE,
    language: "zh-CN",
    env: { fetch: server.fetch, now: clock.now, setTimer: clock.setTimer, clearTimer: clock.clearTimer, channel, hint, random },
  });
  return { client, clock, hint };
}

test("启动时经 /auth/refresh 恢复会话,刷新请求带 X-Requested-With 和 cookie", async () => {
  const server = fakeServer({ refresh: () => json(200, loginBody("t1")) });
  const { client } = makeClient({ server });
  await client.bootstrap();
  assert.equal(client.getSnapshot().status, "authenticated");
  assert.equal(client.getSnapshot().user.handle, "kinda");
  assert.equal(client.accessToken, "t1");
  const call = server.calls.find((one) => one.path === "/auth/refresh");
  assert.equal(call.method, "POST");
  assert.equal(call.headers.get("X-Requested-With"), "XMLHttpRequest");
  assert.equal(call.init.credentials, "same-origin");
  //: 刷新令牌在 HttpOnly cookie 里,脚本不碰:请求体是空的。
  assert.equal(call.init.body, undefined);
});

test("没有「登录过」的标记时,启动不打扰服务;force 时照样试一次", async () => {
  const server = fakeServer({ refresh: () => json(401, { error: { code: "no_session", message: "" } }) });
  const { client } = makeClient({ server, hint: hintStore(false) });
  await client.bootstrap();
  assert.equal(client.getSnapshot().status, "anonymous");
  assert.equal(server.refreshCount, 0);
  await client.bootstrap({ force: true });
  assert.equal(server.refreshCount, 1);
  assert.equal(client.getSnapshot().status, "anonymous");
  //: 强制试过一次就不再试,免得每个组件挂上来都打一次。
  await client.bootstrap({ force: true });
  assert.equal(server.refreshCount, 1);
});

test("启动失败不广播退出 —— 别的标签页可能好好地登录着", async () => {
  const hub = channelHub();
  const server = fakeServer({ refresh: () => json(401, { error: { code: "no_session", message: "" } }) });
  const { client } = makeClient({ server, channel: hub.join() });
  await client.bootstrap();
  assert.equal(client.getSnapshot().status, "anonymous");
  assert.deepEqual(hub.sent, []);
});

test("并发的几个 401 只换来一次刷新,每个原请求用新令牌重放一次", async () => {
  let issued = 0;
  const server = fakeServer({ refresh: () => json(200, loginBody(`t${++issued}`)) });
  const { client } = makeClient({ server });
  await client.bootstrap();
  assert.equal(client.accessToken, "t1");
  server.valid.add("t2"); //: t1 在服务端已经失效(比如服务重启换了签名密钥)。
  let release;
  server.refreshGate = new Promise((resolve) => (release = resolve));
  const pending = [client.request("/me"), client.request("/me"), client.request("/me"), client.request("/me")];
  await flush();
  await flush();
  release();
  const responses = await Promise.all(pending);
  assert.deepEqual(responses.map((response) => response.status), [200, 200, 200, 200]);
  assert.equal(server.refreshCount, 2, "启动一次 + 401 之后一次,并发的 401 不各刷各的");
  const me = server.calls.filter((call) => call.path === "/me");
  assert.equal(me.length, 8, "四个请求,每个恰好重放一次");
  assert.deepEqual(me.slice(4).map((call) => call.auth), Array(4).fill("Bearer t2"));
});

test("重放之后还是 401 就把它交出去,不再刷新、不循环", async () => {
  let issued = 0;
  const server = fakeServer({ refresh: () => json(200, loginBody(`t${++issued}`)) });
  const { client } = makeClient({ server });
  await client.bootstrap();
  const response = await client.request("/me");
  assert.equal(response.status, 401);
  assert.equal(server.calls.filter((call) => call.path === "/me").length, 2);
  assert.equal(server.refreshCount, 2);
});

test("401 之后刷新失败:回到未登录,并通告别的标签页", async () => {
  const hub = channelHub();
  let first = true;
  const server = fakeServer({
    refresh: () => {
      if (first) {
        first = false;
        return json(200, loginBody("t1"));
      }
      return json(401, { error: { code: "refresh_reused", message: "会话已失效" } });
    },
  });
  const { client, hint } = makeClient({ server, channel: hub.join() });
  await client.bootstrap();
  const response = await client.request("/me");
  assert.equal(response.status, 401);
  assert.equal(client.getSnapshot().status, "anonymous");
  assert.equal(client.accessToken, null);
  assert.equal(hint.get(), false);
  assert.deepEqual(hub.sent.at(-1), { type: "logged-out" });
});

test("fetchJson:非 2xx 抛出带 code 与 message 的 CommunityError", async () => {
  const server = fakeServer({ refresh: () => json(200, loginBody("t1")) });
  const { client } = makeClient({ server });
  await client.bootstrap();
  await assert.rejects(client.fetchJson("/nothing"), (error) => {
    assert.ok(error instanceof CommunityError);
    assert.equal(error.status, 404);
    assert.equal(error.code, "not_found");
    assert.equal(error.message, "nope");
    return true;
  });
});

test("fetchJson 按 JSON 发 body,带上语言", async () => {
  const server = fakeServer({ refresh: () => json(200, loginBody("t1")), protectedPaths: ["/me"], valid: new Set(["t1"]) });
  const { client } = makeClient({ server });
  await client.bootstrap();
  const body = await client.fetchJson("/me", { method: "PATCH", json: { display_name: "K" } });
  assert.deepEqual(body, { ok: true, token: "t1" });
  const call = server.calls.at(-1);
  assert.equal(call.headers.get("Content-Type"), "application/json");
  assert.equal(call.headers.get("Accept-Language"), "zh-CN");
  assert.equal(call.init.body, JSON.stringify({ display_name: "K" }));
});

test("到期前 60 秒主动刷新,之后按新的到期时间再排", async () => {
  let issued = 0;
  const server = fakeServer({ refresh: () => json(200, loginBody(`t${++issued}`, 900)) });
  const { client, clock } = makeClient({ server });
  await client.bootstrap();
  assert.deepEqual(clock.pending(), [900_000 - REFRESH_LEEWAY_MS]);
  await clock.advance(900_000 - REFRESH_LEEWAY_MS - 1);
  assert.equal(server.refreshCount, 1, "提前一毫秒还不刷");
  await clock.advance(1);
  assert.equal(server.refreshCount, 2);
  assert.equal(client.accessToken, "t2");
  assert.deepEqual(clock.pending(), [900_000 - REFRESH_LEEWAY_MS]);
});

test("定时器迟到(标签页睡过):发请求前发现快到期,先刷再发", async () => {
  let issued = 0;
  const server = fakeServer({ refresh: () => json(200, loginBody(`t${++issued}`, 900)), valid: new Set(["t2"]) });
  const clock = fakeClock();
  const { client } = makeClient({ server, clock });
  await client.bootstrap();
  //: 定时器被系统挂起:时钟走了,定时器没触发。
  clock.jump(900_000 - 30_000);
  const response = await client.request("/me");
  assert.equal(response.status, 200);
  assert.equal(server.refreshCount, 2);
  assert.equal(server.calls.filter((call) => call.path === "/me").length, 1, "先刷新,不先撞一个 401");
});

test("主动刷新遇到网络错误:令牌还有效就稍后再试,不退出", async () => {
  let attempt = 0;
  const server = fakeServer({
    refresh: () => {
      attempt += 1;
      if (attempt === 1) return json(200, loginBody("t1", 900));
      if (attempt === 2) return json(503, { error: { code: "unavailable", message: "" } });
      return json(200, loginBody("t2", 900));
    },
  });
  const { client, clock } = makeClient({ server });
  await client.bootstrap();
  await clock.advance(900_000 - REFRESH_LEEWAY_MS);
  assert.equal(server.refreshCount, 2);
  assert.equal(client.getSnapshot().status, "authenticated");
  assert.deepEqual(clock.pending(), [RETRY_DELAY_MS]);
  await clock.advance(RETRY_DELAY_MS);
  assert.equal(client.accessToken, "t2");
});

test("一个标签页刷新好了,另一个直接用新令牌、重排定时器,不再自己刷", async () => {
  const hub = channelHub();
  let issued = 0;
  const server = fakeServer({ refresh: () => json(200, loginBody(`t${++issued}`, 900)) });
  const clock = fakeClock();
  //: A 的随机提前量大一些,它的定时器先醒。
  const a = makeClient({ server, clock, channel: hub.join(), random: () => 0.5 });
  const b = makeClient({ server, clock, channel: hub.join(), random: () => 0 });
  await a.client.bootstrap();
  await flush();
  //: B 还没启动,就已经从 A 那里拿到了会话。
  assert.equal(b.client.getSnapshot().status, "authenticated");
  assert.equal(b.client.accessToken, "t1");
  await b.client.bootstrap();
  assert.equal(server.refreshCount, 1, "B 已登录,启动不再刷新");

  //: 两边的定时器差几秒;A 先触发、刷新好、广播,B 收到后重排,自己不刷。
  await clock.advance(900_000 - REFRESH_LEEWAY_MS);
  await flush();
  assert.equal(a.client.accessToken, "t2");
  assert.equal(b.client.accessToken, "t2");
  assert.equal(server.refreshCount, 2, "两个标签页只刷了一次");
});

test("一个标签页退出,另一个跟着退出,不再发请求", async () => {
  const hub = channelHub();
  const server = fakeServer({ refresh: () => json(200, loginBody("t1", 900)) });
  const clock = fakeClock();
  const a = makeClient({ server, clock, channel: hub.join() });
  const b = makeClient({ server, clock, channel: hub.join() });
  await a.client.bootstrap();
  await flush();
  await a.client.logout();
  await flush();
  assert.equal(a.client.getSnapshot().status, "anonymous");
  assert.equal(b.client.getSnapshot().status, "anonymous");
  assert.equal(b.client.accessToken, null);
  assert.deepEqual(clock.pending(), [], "两边的主动刷新都取消了");
  const logout = server.calls.find((call) => call.path === "/auth/logout");
  assert.equal(logout.auth, "Bearer t1");
  assert.equal(logout.headers.get("X-Requested-With"), "XMLHttpRequest");
});

test("旧的会话消息不覆盖更新的令牌", async () => {
  const hub = channelHub();
  const server = fakeServer({ refresh: () => json(200, loginBody("fresh", 900)) });
  const { client } = makeClient({ server, channel: hub.join() });
  await client.bootstrap();
  const other = hub.join();
  other.postMessage({ type: "session", accessToken: "stale", expiresAt: 1, user: USER });
  await flush();
  assert.equal(client.accessToken, "fresh");
});

test("登录成功:进入已登录、记下标记、通告别的页;失败抛出服务的错误", async () => {
  const hub = channelHub();
  const server = fakeServer({ refresh: () => json(401, {}) });
  server.fetch = async (url, init) => {
    const path = url.slice(BASE.length);
    const body = JSON.parse(init.body);
    if (path === "/auth/password/login" && body.password === "right") return json(200, loginBody("t9"));
    return json(400, { error: { code: "invalid_credentials", message: "用户名或密码不对" } });
  };
  const { client, hint } = makeClient({ server, channel: hub.join(), hint: hintStore(false) });
  await assert.rejects(client.login("/auth/password/login", { login: "kinda", password: "wrong" }), /用户名或密码不对/);
  assert.notEqual(client.getSnapshot().status, "authenticated");
  const user = await client.login("/auth/password/login", { login: "kinda", password: "right" });
  assert.equal(user.handle, "kinda");
  assert.equal(client.accessToken, "t9");
  assert.equal(hint.get(), true);
  assert.equal(hub.sent.at(-1).type, "session");
});

test("匿名请求收到 401 不去刷新(本来就没有会话)", async () => {
  const server = fakeServer({ refresh: () => json(401, {}) });
  const { client } = makeClient({ server, hint: hintStore(false) });
  await client.bootstrap();
  const response = await client.request("/me");
  assert.equal(response.status, 401);
  assert.equal(server.refreshCount, 0);
});

test("启动还在路上时发的请求,等启动完成再带令牌发", async () => {
  const server = fakeServer({ refresh: () => json(200, loginBody("t1")), valid: new Set(["t1"]) });
  let release;
  server.refreshGate = new Promise((resolve) => (release = resolve));
  const { client } = makeClient({ server });
  const booting = client.bootstrap();
  const pending = client.request("/me");
  assert.equal(client.getSnapshot().status, "loading");
  release();
  await booting;
  const response = await pending;
  assert.equal(response.status, 200);
  assert.equal(server.calls.find((call) => call.path === "/me").auth, "Bearer t1");
});
