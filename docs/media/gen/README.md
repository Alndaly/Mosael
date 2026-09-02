# 媒体资产生成器

宣传片以**真实产品界面**为主体,生成的图形只做开场、痛点、本地优先、收尾这四段连接
(上一版是九张纯 SVG 幻灯片,没有一帧真实画面,观众看完不知道这东西长什么样)。
配色取 `frontend/src/design/tokens.css` 的浅色「暖纸面」主题。

**换界面截图不用改代码**:把新的同名 png 丢进 `gen/screens/` 即可覆盖默认那套,
需要哪四张见 [`screens/README.md`](screens/README.md)。

依赖:`rsvg-convert`(librsvg)、`ffmpeg`、系统中文字体(PingFang SC / Hiragino Sans GB)。

```bash
python3 docs/media/gen/build_promo.py --preview  # 分镜联络图,先看构图(~7s)
python3 docs/media/gen/build_promo.py            # → docs/media/mosael-promo.mp4(~28s 成片)
python3 docs/media/gen/build_collapse_gif.py  # → collapse.gif(折叠为子图演示)
```

产出:
- `docs/media/collapse-subgraph.gif` —— 框选 → 折叠为子图
- `docs/media/browser-pool.png` / `agent-authorize.png` —— 浏览器池 / 智能体授权闸示意
- `mosael-promo.mp4` —— 完整宣传片(1080p / 约 28s / 2.4MB)

> 联系:1142704468@qq.com
