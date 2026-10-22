// 「宿主要在这一块画东西」的**声明**(P2):一个纯状态机,把各处浮层的声明折算成对原生视图的几条指令。
//
// 背景:原生视图(内嵌浏览器)永远盖在 DOM 上层,所以每个浮层都要单独请它让开。此前这些请求散成
// 四条通道(publishOverlay / publishPanelsHidden / publishCoverPage / publishPagesInset),每加一个
// 浮层就要记得接一次 —— 漏一个的后果是「浮层被网页盖住、点不到」,而且不报错。
//
// 这里只做一件事:输入是若干条**声明**(谁、要哪种让法、开还是关),输出是一组**指令**
// (让哪些原因生效、面板要不要藏、右侧让出多少)。Electron 那边的调用归 accountViews,
// 这里不碰任何 Electron —— 能单独测,规则也只有一份。

/** 让法。前三种都是「前台网页让开」的不同理由(可以同时成立),`panels` 与 `inset` 是另外两件事。 */
const KINDS = Object.freeze(["region", "cover", "overlay", "panels", "inset"]);

/** 能不能同时有多条声明(同一个 kind 下按 id 分别算)。 */
function createHostLayers() {
  /** id → { kind, active, width } */
  const claims = new Map();

  function directives() {
    const reasons = new Set();
    let panelsHidden = false;
    let insetRight = 0;
    for (const claim of claims.values()) {
      if (!claim.active) continue;
      if (claim.kind === "panels") panelsHidden = true;
      else if (claim.kind === "inset") insetRight = Math.max(insetRight, Number(claim.width) || 0);
      else reasons.add(claim.kind);
    }
    return { reasons: [...reasons], panelsHidden, insetRight };
  }

  return {
    /** 一条声明。同 id 后写的覆盖前写的(浮层自己开/关,不叠加)。 */
    set(id, claim) {
      const key = String(id || "").trim();
      if (!key) throw new Error("hostLayers: every claim needs an id");
      const kind = String(claim?.kind || "");
      if (!KINDS.includes(kind)) throw new Error(`hostLayers: unknown kind ${kind}`);
      claims.set(key, {
        kind,
        active: Boolean(claim?.active),
        width: Number(claim?.width) || 0,
      });
      return directives();
    },
    /** 撤掉某条声明(浮层卸载时调,避免它一直占着让位)。 */
    clear(id) {
      claims.delete(String(id || "").trim());
      return directives();
    },
    directives,
    size: () => claims.size,
  };
}

module.exports = { createHostLayers, KINDS };
