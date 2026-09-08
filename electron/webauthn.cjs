// 内嵌浏览器里的 WebAuthn(passkey)。
//
// Electron 44 给了两样东西,**只有两样**:
//
//   app.configureWebAuthn({ touchID })    macOS 的平台认证器(Secure Enclave)
//   session 的 select-webauthn-account    一次请求解出多个可发现凭据时,由我们来选
//
// 没有给的是**手机/跨设备(hybrid,俗称扫码那条)**:它的二维码载荷和蓝牙广播都在 Chromium
// 的 AuthenticatorRequestDialogModel 里生成,Electron 没有把它暴露出来。所以那条路不是
// "界面难做",是**根本没有可以挂界面的地方** —— 我们既拿不到二维码,也没法告诉 Chromium
// "走 hybrid"。别的浏览器能做,是因为它们自己就是那层 UI。
//
// Touch ID 这条要三个前提同时成立,缺一不可:
//
//   1. 应用**已签名**,且 entitlements 里有 keychain-access-groups
//   2. 该 group 形如 <TEAM_ID>.<BUNDLE_ID>.webauthn,并与这里传的值完全一致
//   3. 机器有 Secure Enclave(Apple silicon,或带 T2 的 Intel Mac)
//
// 少任何一条,configureWebAuthn 都不会让 passkey 可用 —— 而它**不会报错**,只是
// isUserVerifyingPlatformAuthenticatorAvailable() 继续答 false。所以这里在开之前把条件
// 判掉并留一条日志,免得以后有人对着"为什么没生效"猜。
//
// 还有一条要说清楚:这里存的凭据是**设备绑定、不跟 iCloud 同步**的,而且 Electron 按 session
// 分区隔离。所以它救不了"用户在手机上已有的那把 Google passkey" —— 它的用途是让用户**在
// Mosael 里新注册一把**,之后在这个档案里就能用 Touch ID 登录。
const { app, dialog, session } = require("electron");

/** 签名后的 Team ID。没签名就没有它 —— 那时整条链都不成立。 */
const TEAM_ID = (process.env.MOSAEL_TEAM_ID || "").trim();

/** 与 package.json 的 `build.appId` 必须一致 —— keychain group 是拿它拼的,对不上就静默失效。
 *  `electron/webauthn.test.ts` 盯着这两个别分岔。 */
const BUNDLE_ID = "dev.mosael.app";

function log(...args) {
  if (process.env.MOSAEL_DEBUG) console.log("[webauthn]", ...args);
}

/** 平台认证器是否有可能可用。**只判我们能判的那几条**,判不了的交给 Electron。 */
function touchIdPossible() {
  if (process.platform !== "darwin") return "";
  if (!TEAM_ID) return "";
  return `${TEAM_ID}.${BUNDLE_ID}.webauthn`;
}

/**
 * 开启平台认证器。**没签名时什么也不做** —— 这是当前构建的实际情况
 * (package.json 里 mac.identity 是 null,CI 也显式关掉了签名发现)。
 */
function configurePlatformAuthenticator() {
  const group = touchIdPossible();
  if (!group) {
    log("平台认证器未启用:需要 macOS + 已签名(MOSAEL_TEAM_ID)");
    return false;
  }
  try {
    app.configureWebAuthn({
      touchID: {
        keychainAccessGroup: group,
        promptReason: "verify your identity on $1",
      },
    });
    log("平台认证器已启用:", group);
    return true;
  } catch (error) {
    // 没有对应的 entitlement 时会抛。这不是致命错误:passkey 用不了,别的照常。
    log("平台认证器启用失败:", String(error).slice(0, 200));
    return false;
  }
}

/**
 * 多凭据选择。
 *
 * **不注册监听器的话,请求会被直接取消**(页面收到 NotAllowedError)—— 上一版我把这条说成
 * "走不通",是错的:它不是不通,是我们从来没接。
 *
 * 只有一把凭据时自动选中:那是登录档案里的绝对常态,再弹一个"请选择"的框纯属噪音。
 * 多把时用系统对话框问 —— 这条路一年也走不了几次,为它做一套渲染层 UI 不值得,而系统框
 * 至少是**同步、可见、可取消**的。
 */
function handleAccountSelection(partition) {
  const target = session.fromPartition(partition);
  if (target.__mosaelWebauthnBound) return;
  target.__mosaelWebauthnBound = true;
  target.on("select-webauthn-account", (event, details, callback) => {
    const accounts = details.accounts || [];
    try {
      if (accounts.length <= 1) {
        callback(accounts[0]?.credentialId);
        return;
      }
      const labels = accounts.map((a) => a.name || a.displayName || a.credentialId.slice(0, 12));
      const picked = dialog.showMessageBoxSync({
        type: "question",
        title: "选择账号",
        message: `${details.relyingPartyId} 上有多个可用账号`,
        buttons: [...labels, "取消"],
        cancelId: labels.length,
        defaultId: 0,
      });
      callback(picked < labels.length ? accounts[picked].credentialId : undefined);
    } catch (error) {
      log("选择失败:", String(error).slice(0, 200));
      // **一定要回调一次。** 不回调请求就永远挂着 —— 正是我们要消灭的那种状态。
      callback(undefined);
    }
  });
}

module.exports = { configurePlatformAuthenticator, handleAccountSelection, touchIdPossible };
