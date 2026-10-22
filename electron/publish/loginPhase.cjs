// 「登录」这件事的显式状态机(P3)。
//
// 此前它是一堆 if:亮视图 → 每 5 秒问一次 checkLogin → 超时/被收起/被停各写一行日志。分支散在
// publishWorker.openLogin 里,失败时只留下「not logged in yet at <url>」这一句 —— 视频号那几轮排查
// 就是因为看不出它停在「还没开始」「在等用户」「判据一直说不」还是「判据自己抛错了」。
//
// 这里只做**状态与原因**,不做 IO:
//
//   opening   正在建视图 / 导航到登录页
//   waiting   登录页已经亮出来,等用户操作
//   verifying 正在问 adapter.checkLogin()
//   bound     认出了已登录(终态)
//   failed    没登上(终态,带原因)
//
// 失败原因固定几种,每一种都对应一个**下一步**:timeout(重新登录 / 换身份档)、dismissed(用户自己
// 收起了)、stopped(被停掉)、error(判据抛错,带上错误文本)、switched(同一个账号换了新一代登录)。
const TERMINAL = new Set(["bound", "failed"]);

const FAIL_REASONS = new Set(["timeout", "dismissed", "stopped", "error", "switched"]);

/**
 * @param {object} options
 * @param {() => number} [options.now] 取时间(测试注入)
 * @param {(event: object) => void} [options.onChange] 每次状态真的变了就回调一次
 */
function createLoginFlow(options = {}) {
  const now = typeof options.now === "function" ? options.now : Date.now;
  const onChange = typeof options.onChange === "function" ? options.onChange : () => undefined;
  let phase = "opening";
  let reason = "";
  let detail = "";
  let since = now();
  let checks = 0;
  let lastError = "";

  const snapshot = () => ({ phase, reason, detail, since, checks, lastError, terminal: TERMINAL.has(phase) });

  function move(next, nextReason = "", nextDetail = "") {
    if (TERMINAL.has(phase)) return false;               // 终态不再变:绑定成功 / 失败都是结论
    if (next === phase && nextReason === reason && nextDetail === detail) return false;
    phase = next;
    reason = nextReason;
    detail = nextDetail;
    since = now();
    onChange(snapshot());
    return true;
  }

  return {
    state: snapshot,
    /** 视图亮出来了 / 登录页开始加载。 */
    opened() {
      return move("waiting");
    },
    /** 开始问一次判据(由轮询驱动)。 */
    verifying() {
      if (TERMINAL.has(phase)) return false;
      checks += 1;
      return move("verifying");
    },
    /** 这一拍判据说「还没登录」:回到等待,并记下这一拍看到的地址(排查靠它)。 */
    notYet(where = "") {
      lastError = "";
      return move("waiting", "", String(where || "").slice(0, 200));
    },
    /** 这一拍判据抛错:不直接判失败(页面可能还在加载),但把错误留下来给下一次日志。 */
    checkFailed(error) {
      lastError = String((error && error.message) || error || "").slice(0, 200);
      return move("waiting", "", lastError);
    },
    /** 认出来了。 */
    bound() {
      return move("bound");
    },
    fail(reason, detail = "") {
      const why = FAIL_REASONS.has(String(reason)) ? String(reason) : "error";
      return move("failed", why, String(detail || "").slice(0, 200));
    },
    isTerminal: () => TERMINAL.has(phase),
  };
}

module.exports = { createLoginFlow, FAIL_REASONS };
