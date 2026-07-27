/**
 * 更名(Mibu → Open Studio)的 localStorage 键迁移:`mibu.*` → `openstudio.*`。
 *
 * 这些键存着登录 token、服务器地址、外观/偏好、编辑器面板尺寸、会话选择等。单改代码里的键名
 * 而不迁移,用户下次打开就是「被登出 + 所有偏好复位」。
 *
 * 必须在**任何模块读取这些键之前**执行:api/client.ts 在模块加载时就读 token 与服务器地址
 * (`let authToken = localStorage.getItem(...)`),晚一步迁移就等于没迁。因此本模块在
 * main.tsx 的第一行被导入 —— ES 模块按导入顺序求值,它先于 App 及其依赖链跑完。
 *
 * 按前缀整体重写,所以动态键(mibu.agent.session.<ws>、mibu.agent.allow.<key> 等)一并覆盖。
 * 幂等:老键搬完即删;新键已存在时不覆盖(以新值为准)。
 */
// 两种历史前缀都要覆盖:点号族(mibu.auth.token 等)与冒号族(mibu:workspace、
// mibu:settings-section)。分隔符保持不变,只换前面的应用名。
const LEGACY_PREFIXES = ["mibu.", "mibu:"] as const;
const NAME = "openstudio";

export function migrateLegacyStorageKeys(): void {
  try {
    const storage = window.localStorage;
    // 先收集再改写:直接在遍历中增删会打乱 key(i) 的下标。
    const legacyKeys: string[] = [];
    for (let i = 0; i < storage.length; i++) {
      const key = storage.key(i);
      if (key && LEGACY_PREFIXES.some((prefix) => key.startsWith(prefix))) legacyKeys.push(key);
    }
    for (const legacyKey of legacyKeys) {
      const nextKey = NAME + legacyKey.slice("mibu".length); // 分隔符(. 或 :)随后半段一起保留
      const value = storage.getItem(legacyKey);
      if (value !== null && storage.getItem(nextKey) === null) storage.setItem(nextKey, value);
      storage.removeItem(legacyKey);
    }
  } catch {
    /* 存储不可用(隐私模式等)——迁移只是尽力而为,不该阻断启动。 */
  }
}

migrateLegacyStorageKeys();
