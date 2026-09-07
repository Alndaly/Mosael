# 前端 lint 的三个选择

## 为什么是 oxlint,不是 eslint

这个项目在 **TypeScript 7.0**,而 `typescript-eslint` 目前对 TS 7.0 是**硬阻塞** —— 连
`@typescript-eslint/parser` 单独加载都会抛
`typescript-eslint does not support TS 7.0`(见 typescript-eslint#10940)。没有它就没有能
读 `.tsx` 的解析器,eslint 在这个仓库里跑不起来。

oxlint 是 Rust 实现,自带 TS/TSX 解析,不依赖 `typescript` 这个包,所以不受这条约束。
等 typescript-eslint 支持 TS 7 之后可以再评估换回去 —— 那时规则名基本是对得上的。

## 为什么只选这十四条

打开 `correctness` 整类会得到 **358 条**,其中大半来自 React Compiler 那套规则
(`refs` / `set-state-in-effect` / `immutability` / `preserve-manual-memoization`)——
这个代码库成形于它们之前,而它们要求的是**改写组件结构**,不是改几行。

判据和后端那份 ruff 配置一样:**选能抓缺陷的,不选风格,而且要能收到零。**
一个开局几百条警告的 lint,和没有 lint 是同一回事 —— 没人会看,于是真的那几条也一起淹掉。
现在 `pnpm lint` 退出码是 0,所以它能当闸用。

## 明确搁置的两组(不是"以后再说",是判断题)

**`react-hooks/exhaustive-deps`(37 处)。** 仓库里本来就有 22 处
`eslint-disable react-hooks/exhaustive-deps` —— 也就是说这条规则一直被当作存在,只是从来
没有 linter 去执行它。补依赖数组会改变重算时机,可能引出循环;该逐处看、每处配一条测试,
不该批量开。

**React Compiler 那套(约 120 处)。** 同上,而且代价更大:`set-state-in-effect` 要求把
派生状态改成 render 期计算,那是组件重写。想收的话按文件推进,别按规则推进。

## 跑

```bash
pnpm --dir frontend lint      # 检查
pnpm --dir frontend lint:fix  # 只应用安全修复
```

`--fix-dangerously` **不进脚本**:它会删掉"声明了但没读"的整个表达式,包括带副作用的
`useQuery`。这次清理里它删了两个,人工核对后确认两个都是**与自己子组件同 key、同 URL、
同轮询间隔的重复观察者**(React Query 按 key 去重,删掉无可观察变化)—— 但那是核对出来的
结论,不是它能保证的。
