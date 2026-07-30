# 为什么 pi-ai / pi-agent-core 钉在 0.80.10

升到 0.82.1 后,**每一轮对话都会失败**,用户侧表现为「智能体执行失败」,详情里是:

```
TypeError: ModelsImpl is not a constructor
```

## 定位过程

`createModels()` 内部 `new ModelsImpl(options)`,而 `ModelsImpl` 在打包产物里被放进了惰性
初始化块,调用发生时还是 `undefined`。分离变量后的实测矩阵:

| pi-ai | 打包方式 | 结果 |
|---|---|---|
| 0.80.10 | `--format=cjs`(现行配置) | ✅ 正常触网 |
| 0.82.1 | `--format=cjs` | ❌ ModelsImpl is not a constructor |
| 0.82.1 | `--format=esm` + createRequire banner | ❌ 同上 |
| 0.82.1 | `--external:@earendil-works/*`(不打包) | ✅ 正常触网 |

最后一行是关键:**不是版本本身有问题,是 0.82 的模块结构与「打成单文件」不兼容**
(0.82 重排了模块,产物从 6.4MB 降到 1.1MB,惰性块之间形成了 esbuild 解不开的初始化顺序)。

## 为什么不走 external

pi-ai 有 11 个传递依赖。external 意味着随包分发一棵可解析的 node_modules 树,而我们用 pnpm
(符号链接结构),electron-builder 打包这类结构很麻烦;产物也会从一个 6.4MB 单文件变成一堆文件。
代价大于收益。

## 什么时候可以再试

`pnpm --dir agent-sidecar test:bundle` 就是判据 —— 它驱动真实产物跑一轮,要求**正面证据**
(必须走到发起网络请求),而不是只检查某个错误串不出现。升级后跑一次即可知道能不能解禁。
