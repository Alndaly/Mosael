# 媒体资产生成器(代码生成,不录屏)

本目录的脚本按品牌设计系统(`frontend/src/design/tokens.css` 暗色)用 SVG 排版,
再经 `rsvg-convert` 渲成 PNG、`ffmpeg` 合成,产出宣传片与文档配图。改文案/配色/时长
只改脚本重跑即可。

依赖:`rsvg-convert`(librsvg)、`ffmpeg`、系统中文字体(PingFang SC / Hiragino Sans GB)。

```bash
python3 docs/media/gen/build_promo.py         # → open-studio-promo.mp4(~30s 宣传片)
python3 docs/media/gen/build_collapse_gif.py  # → collapse.gif(折叠为子图演示)
```

产出:
- `docs/media/collapse-subgraph.gif` —— 框选 → 折叠为子图
- `docs/media/browser-pool.png` / `agent-authorize.png` —— 浏览器池 / 智能体授权闸示意
- `open-studio-promo.mp4` —— 完整宣传片(体积较大,不入库;按需发布)

> 联系:1142704468@qq.com
