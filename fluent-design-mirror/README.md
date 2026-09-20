# fluent2.microsoft.design mirror

这是给 Agent 使用的 Fluent 2 设计系统资料镜像。主要语料位于 `pages/`，已经从站点的预渲染 HTML（`<main id="main-content">`）清洗成 Markdown；正文中的图片优先改写为 `assets/` 下的相对路径。

## 使用方式

从仓库根目录执行：

```powershell
python fluent-design-mirror\refresh.py --workers 10
```

首次运行会下载 sitemap 列出的全部页面以及正文引用的 CDN 图片。后续只重建 Markdown、不重新下载已有资源时：

```powershell
python fluent-design-mirror\refresh.py --workers 10 --no-assets
```

需要强制重新抓取全部资源时，加上 `--refresh`。

## 目录

```text
pages/       Agent 主要读取的 Markdown 页面
assets/      Markdown 引用的本地图片
metadata/    抓取版本、页面清单和资源清单
refresh.py   刷新脚本，默认把输出写回当前目录
manifest.json
```

原始页面 HTML 默认不保留。需要调试数据映射时，可以加 `--keep-html`，原始数据会写入 `metadata/raw-pages/`。

## 当前范围

镜像包含 sitemap 列出的全部公开页面（首页、foundations、styles、components、content-engineering、get-started 等），不包含员工登录后的内部内容、搜索结果和分析脚本。抓取范围遵守站点的 `robots.txt`。

站点是 Astro 构建，正文是服务端渲染好的静态 HTML，无需执行 JavaScript。交互式组件演示（`astro-island`）只保留其静态 SSR 输出。图片 URL 中的 Astro `/_image?href=...` 优化器会被还原为原始 CDN 地址后再下载。

资源可能因源站删除而返回 404；这类图片不会被伪造替换，Markdown 会保留原始 URL，错误记录在 `metadata/assets.json`。

生成内容通过仓库本地的 `.git/info/exclude` 排除；`README.md` 和 `refresh.py` 可以提交到 Git，方便共享刷新方式。重新生成时脚本会复用已有文件，并以 sitemap 中最新的 `lastmod` 更新 `manifest.json`。
