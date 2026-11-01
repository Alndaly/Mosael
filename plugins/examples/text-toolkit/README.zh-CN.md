# 文本小工具

全部在本机计算的文本小工具:统计字数与口播时长、把口播稿断成字幕行、按字数截短、清理文案、
Markdown 转纯文本，以及提取话题标签、网址、@ 提及和邮箱。

## 安装

这个示例随仓库提供。在「插件 → 从文件夹安装」里选择 `plugins/examples/text-toolkit`，清单是
`mosael.plugin.json`。它**不申请任何权限**，没有本地服务，也不联网。

## 工具

全部只读，可给智能体、工作流和画板使用。

| 工具 | 做什么 | 主要参数 |
| --- | --- | --- |
| `word_count` | 统计字数、词数与预计口播时长。中日韩文一个字算一个词;中文约每秒 4.5 字,英文约每分钟 150 词。 | `text` |
| `split_lines` | 把口播稿断成字幕行:先按句末,再按逗号、顿号这类停顿切,英文不在词中间断;默认去掉行尾标点。 | `text`、`max_chars`(默认 16)、`keep_punctuation` |
| `truncate` | 截到指定字数以内,尽量停在停顿或词的边界上。 | `text`、`max_chars`(默认 20)、`ellipsis`(默认 `…`) |
| `clean_text` | 去掉零宽字符、多余空格和空行,全角字母数字转半角;可选中文后的全角标点、中英文之间加空格、去表情。 | `text`、`chinese_punctuation`、`space_between`、`remove_emoji` |
| `strip_markdown` | 去掉标题、加粗、链接、引用和列表记号,得到能直接粘贴的纯文本;列表变成 `• `,代码块保留。 | `text`、`keep_urls` |
| `extract_hashtags` | 按出现顺序提取 `#话题#` 与 `#hashtag`;大小写不同的算一个,纯数字的 `#1` 不算。 | `text` |
| `extract_links` | 按顺序提取网址、@ 提及和邮箱,重复的只留一次。 | `text` |

每个工具还返回一行 `summary`;工作流节点的输出已在清单里声明,不用再写第二份定义。

## 工作流与画板

把节点拖进工作流,或在画板格子里使用。画板默认暴露 `summary`;节点输出还提供
`split_lines.text`、`truncate.text`、`clean_text.text`、`strip_markdown.text`、
`extract_hashtags.hashtags`、`extract_links.urls` 和 `word_count.summary`。

## 说明

- 纯本地计算:不需要模型、API Key,也不上传内容。
- 参数上限与输出名在 `mosael.plugin.json`;实现是 `tools/main.py`。
