# docmirror4a

给 Agent 使用的文档镜像爬取脚本集合。每个子目录对应一个目标站点的镜像，只包含可提交的 `refresh.py`（抓取/转换脚本）和 `README.md`（使用说明）。抓取产物（`pages/`、`assets/`、`metadata/`、`manifest.json`）保留在各自的工作目录，不进入本仓库。

## 子目录

| 目录 | 目标站点 | 说明 |
| --- | --- | --- |
| `android-docs-mirror/` | Android 开发者文档 | 镜像 Android developer 文档 |
| `kotlin-docs-mirror/` | Kotlin 文档 | 镜像 Kotlin 语言文档 |
| `kmp-docs-mirror/` | Kotlin Multiplatform 文档 | 镜像 KMP 指南、Compose Multiplatform 与其 API 参考 |
| `m3-material-mirror/` | m3.material.io | 镜像 Material 3 设计资料 |
| `fluent-design-mirror/` | fluent2.microsoft.design | 镜像 Fluent 2 设计系统资料 |

各站点的具体用法见对应子目录的 `README.md`。

## 通用模式

所有脚本均为零依赖的 Python 3（仅用标准库），统一约定：

- 抓取目标站点的公开页面，清洗成 Markdown 写入 `pages/`
- 把正文引用的图片下载到 `assets/`，并将 Markdown 中的 URL 改写为相对路径
- 抓取元数据写入 `metadata/`，快照信息写入 `manifest.json`
- 抓取范围遵守各站点的 `robots.txt`，只镜像公开内容

典型用法（在镜像所在目录执行）：

```powershell
python <name>-mirror\refresh.py --workers 10
```

详见各子目录 README。
