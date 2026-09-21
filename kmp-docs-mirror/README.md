# KMP 文档镜像

给 Agent 使用的 Kotlin Multiplatform 与 Compose Multiplatform 官方文档镜像。语料位于 `pages/`，已从站点
HTML 清洗成 Markdown，正文图片改写为 `assets/` 下的相对路径。对应 KMP 文档（Kotlin 2.4.20）。

## 使用方式

先在 `pages/` 下 grep 关键词，命中后读该文件头部的来源 URL 回到官方页面核对：

```powershell
rg "expect fun" kmp-docs-mirror\pages
```

每页第一行记录来源 URL、抓取时间和上游 `Last-Modified`。`pages/INDEX.md` 按 KMP 指南、Compose
Multiplatform、API 参考三组列出主题到文件的映射，是进入这份语料的入口。

**文档描述的是框架与库的意图。某个 API 在本项目钉住的版本里是否存在、签名是什么，以本机 Gradle 缓存里的
构件为准。** 镜像对应上游当前的发布版本，与 `gradle/libs.versions.toml` 钉住的版本未必一致。

## 刷新

从仓库根目录执行：

```powershell
python kmp-docs-mirror\refresh.py --workers 10
```

| 参数 | 作用 |
| --- | --- |
| `--workers N` | 并发请求数，上限 10 |
| `--max-age H` | 镜像在 H 小时内视为新鲜，跳过请求，默认 24；`0` 表示每页都发条件请求 |
| `--refresh` | 忽略缓存重新下载全部内容 |
| `--no-assets` | 不下载正文图片 |
| `--no-api` | 跳过 Dokka API 参考，只刷新指南 |
| `--full-api` | API 参考连成员页一并抓取，见下文范围一节 |
| `--check` | 只发条件请求，报告上游哪些页变过，不写文件 |
| `--verify` | 抽样对照源 HTML，输出保真度报告 |

全部成功退出码为 0，有任何页面或图片失败为非 0。失败写入 `metadata/failures.json`，含 URL、状态码、累计重试
次数和最后一次时间；同一 URL 后续成功时该条目被移除。

刷新策略分三层。**新鲜窗口**：`--max-age` 之内的页面不发请求，一次完整刷新之后的重跑因此在一秒内结束。
**条件请求**：窗口过期后带 `If-None-Match` 与 `If-Modified-Since` 请求，304 保留本地 Markdown 不重新渲染。
**断点续跑**：每页落盘时追加一行到 `metadata/progress.jsonl`，中途被打断后重跑会把它折回 `cache.json`，已完成
的部分不再下载。

范围收窄或上游删页之后，`pages/` 下不再被认领的 Markdown 会被删除。留着它们与仍然有效的页面无从分辨。

## 目录

```text
pages/       Agent 主要读取的 Markdown，INDEX.md 是入口
assets/      正文引用的图片，按原 URL 路径存放
metadata/    HelpTOC、config、sitemap 快照，抓取缓存、进度与失败账本
manifest.json
refresh.py
```

## 范围

`https://kotlinlang.org/robots.txt` 没有任何 `Disallow` 规则，只声明 sitemap，抓取范围不受它限制。范围由下面
三组划定，其余一律不抓。

**KMP 指南（74 页）**、**Compose Multiplatform（60 页）** 两组取自 `/docs/multiplatform/` 下的
`HelpTOC.json`。Compose 组按导航标题 `Compose Multiplatform UI framework` 定位，改名直接报错；其余本地页面
全部归入 KMP 组，新加的章节会被自动收录而不是悄悄丢掉。站外链接（案例、发布说明、路线图博客）与指向其他
docset 的绝对路径链接（如 `/docs/wasm-get-started.html`）不在范围内。

**API 参考（267 页）** 取自 Dokka 站点 `/api/compose-multiplatform/`，静态 HTML，可以直接抓。默认只抓包索引页
与类型索引页：类型页已经列出每个成员的完整签名与一句说明，而单独的成员页另有约 1800 个。需要成员页的长篇
KDoc 时加 `--full-api`。

以下不在范围内。**缺失不代表官方没写**，需要时到 kotlinlang.org 上查：

- 主站 `/docs/` 的 Native、JS、Wasm 语言与平台指南
- Ktor、kotlinx.serialization 等库指南与构建工具文档
- 教程、社区、版本发布公告等非手册页
- `api/core`、`api/kotlinx.coroutines` 等其他 Dokka 站点

## 清洗规则

本站点是 React 壳加内容直出的混合形态，抓取时按页面的实际形状分三种处理。文章页要带 `Accept: text/html`
请求头才会返回服务端渲染好的正文，否则只拿到 4KB 空壳；落地与导航页正文根本不在 HTML 里，内容是一份由壳上
`data-topic` 属性指名的同目录 JSON。三种形状：

- 文章页取 `<article class="article">`，与主站 `/docs/` 同一套 Writerside 模板，同一套清洗规则。
- 导航页把 `data-topic` JSON 里的标题、副标题、卡片组与上下页链接渲染成 Markdown，卡片图标走同一套图片下载。
- API 参考取 `<div class="main-content">`，与主站同一套 Dokka 清洗规则，按源集去重只保留一份。

三侧共同丢弃脚本、样式、`<nav>`、`<header>`、`<footer>`、按钮与表单。此外：

- 文章页丢弃页尾的最后修改日期、上一页与下一页导航、反馈组件、评论容器和视频播放器。
- API 参考丢弃面包屑、复制按钮、锚点图标、源码链接、源集切换标签和站点导航。

保留的部分：代码块原样保留并带上语言标记，表格转成 Markdown 表格，`aside` 提示转成引用块，列表按层级缩进，
代码块嵌在列表项里时随该项缩进。表格单元格里的代码示例以内联形式保留在行内，不单独成块。

## 保真度

```powershell
python kmp-docs-mirror\refresh.py --verify --sample 30
```

按三组分层抽样，重新取源对照，逐页打印 `产物/源`，末尾给出分组汇总、缺口最大的页面和通过与否，
完整数据写入 `metadata/verify.json`。

三类页面的口径不同，因为它们不可比。**文章页**比代码块、标题、表格三项计数，要求逐项相等，标题与表格只数
围栏代码块之外的正文，避免 Gradle 片段里的 `#` 注释被当成标题。**导航页**比 JSON 里声明的链接是否逐个出现在
Markdown 里。**API 页**比声明与小节是否齐全：取源页每个成员行的链接目标，逐个确认出现在 Markdown 里，再确认
每个小节标题都在。API 页不数签名块，Dokka 一个声明按源集渲染多遍而镜像只留一份，数签名块会在每一页上报出
恒定的缺口，这样的报告比没有报告更糟。

**判据是零缺口**：任何一页在自己那套口径下少一项即为未通过，退出码非 0。改动清洗规则之后重跑一次，这是这份
镜像可信的凭据。已知残留：`multiplatform-cocoapods-dsl-reference` 页表格单元格内嵌一例代码，内容完整保留在
表格行内，verify 按块计数少 1。

## 与 Git 的关系

`pages/`、`assets/`、`metadata/`、`manifest.json` 由仓库根目录的 `.gitignore` 排除。`README.md` 与
`refresh.py` 可以提交，方便共享刷新方式。脚本只用 Python 标准库，没有额外依赖。
