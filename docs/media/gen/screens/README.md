# 放这里的截图会覆盖默认素材

`build_promo.py` 优先读本目录里的同名 png,没有才回退到 `website/public/media/screens/`。

需要的四张(**16:10 或 16:9,越宽越好;暗色浅色都行,但四张要统一**):

| 文件名 | 拍什么 | 要点 |
| --- | --- | --- |
| `editor.png` | 剪辑页 | 时间线要有多条轨:底轨接龙 + 一个画中画 + 字幕轨 |
| `ai-chat.png` | AI Studio 对话 | **要有真实往来内容,并且带一张确认卡** —— 空面板讲不出"AI 能动你的工程" |
| `workflows.png` | 工作流画布 | 节点连成一条完整链路,别是空画布 |
| `publish.png` | 发布页 | **要有发布记录**,空状态没有说服力 |

截完直接重跑:

```bash
python3 docs/media/gen/build_promo.py --preview   # 先看构图(约 7s)
python3 docs/media/gen/build_promo.py             # 出成片(约 10s)
```
