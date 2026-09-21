# WinRT 原生能力速查映射

给 Agent 用的：桌面应用常用原生能力 → WinRT 命名空间 → 在 kotlin-winrt 里到哪找 →
有没有被验证过。回答"这个原生行为叫什么、能不能调"，不动手翻 Learn 也能定位。

前提：`kotlin-winrt` 是投影，WinRT 原表面 1:1 翻成 Kotlin。预置投影只有四块
（Windows SDK、Windows App SDK 2.2.0、XAML、WebView2），表里"投影面内"指的就是这四块。
**sample 里没出现 ≠ 调不了**，只代表没人跑过；真要用，在 Windows 上构建一次，绑定即落盘。

状态说明：✅ sample 验证过（JVM + Native 双路冒烟） / ◐ 投影面内、未见 sample /
❌ 未见，动手前先确认在不在投影范围。

## 应用框架

| 能力 | WinRT 命名空间 | kotlin-winrt 对应 | 状态 | 备注 |
| --- | --- | --- | --- | --- |
| 应用启动、窗口、XAML 入口 | `Microsoft.UI.Xaml` | `winrt-samples` WinUi 系列 sample | ✅ | `Application.start` + `onLaunched`，双路都跑 |
| XAML 标记（字符串转 UI） | `Microsoft.UI.Xaml.Markup.XamlReader` | `WebView2Sample.kt` + 测试断言 | ✅ | 不是只能手写代码，XAML 字符串可解析 |
| 常用 XAML 控件 | `Microsoft.UI.Xaml.Controls` | `WinUiControlsSample`（Button/TextBox/ComboBox/ListView/TabView/Slider/MenuFlyout…约 20 个） | ✅ | 够搭常规界面；冷门控件未验 |
| 窗口控制（大小、模式、标题栏） | `Microsoft.UI.Windowing.AppWindow` | `WindowsAppSdkProjectionConsumer` fixture | ◐ | 只到编译消费，无运行时 sample |
| 线程调度 | `Microsoft.UI.Dispatching.DispatcherQueue` | runtime 基础设施多处使用 | ✅ | UI 线程封送走它 |
| 协议/文件激活 | `…ActivatedEventArgs`（`onActivated`） | samples 只覆盖 `onLaunched` | ◐ | 启动 ✅，协议/文件关联激活未见 |

## 系统集成

| 能力 | WinRT 命名空间 | kotlin-winrt 对应 | 状态 | 备注 |
| --- | --- | --- | --- | --- |
| Toast 通知 | 打包应用走 `Microsoft.Windows.AppNotifications`，未打包走 `Windows.UI.Notifications` | 无 | ❌ | **先定打包形态再选 API**，两者不互通；packaged 需包标识 |
| 徽章、开始菜单磁贴 | `Microsoft.Windows.BadgeNotification` / `Windows.UI.StartScreen` | 无 | ❌ | 同上，跟打包形态绑定 |
| 文件/文件夹选择器 | `Windows.Storage.Pickers` | 无 | ◐ | 桌面应用要点：先 `InitializeWithWindow` 绑窗口句柄，否则起不来 |
| 剪贴板、分享 | `Windows.ApplicationModel.DataTransfer` | 仅 `winui-kmp-library` 构建依赖，无用法 | ◐ | API 面全（Clipboard/DataPackage 都在 Windows SDK 投影内） |
| 开机自启动 | `Windows.ApplicationModel.StartupTask` | 无 | ❌ | 仅打包应用可用；未打包改走注册表/计划任务（Win32 路） |
| 本地设置、应用数据 | `Windows.ApplicationModel.ApplicationData` | 无 | ◐ | 简单配置直接读写文件更省事，非必须用它 |
| 后台任务 | `Windows.ApplicationModel.Background` | 无 | ❌ | 复杂且跟包标识强绑定，需要时单独立项验证 |
| 小组件 | `Microsoft.Windows.Widgets` | 无 | ❌ | WinAppSDK 独占；优先级低就先不碰 |

## 材质与内嵌网页

| 能力 | WinRT 命名空间 | kotlin-winrt 对应 | 状态 | 备注 |
| --- | --- | --- | --- | --- |
| Mica / Acrylic | `Microsoft.UI.Composition.SystemBackdrops`（XAML 侧 `MicaBackdrop`） | `WebView2Sample.kt` 用 `MicaBackdrop` + `MicaKind`，测试断言 | ✅ | **这是"看起来原生"最便宜的一笔**；注意 compose-fluent 自绘的是假 Mica，真 Mica 必须走这里 |
| WebView2 内嵌网页 | `Microsoft.UI.Xaml.Controls.WebView2` + `Microsoft.Web.WebView2.Core` | `WebView2Sample`（离线 HTML + 地址栏），JVM/Native 双路 | ✅ | 需本机 Evergreen Runtime；用户数据目录已隔离到 build 下 |
| 传统 Win32 行为（全局热键、托盘图标等） | 非 WinRT，走 Win32 API | `winrt-runtime` 经 FFM 建了 Win32/COM 桥 | ◐ | 桥在，逐个 API 现接；托盘图标先看 WinAppSDK 有没有封装，没有就 Win32 直调 |

## 动手时的查法（按顺序）

1. 先看 `winrt-samples/src/winuiMain/.../samples/` 有没有现成 sample，有就抄。
2. 没有，看 Learn 上对应概念页（每个能力 1–2 页足够，不用镜像，单页现抓）。
3. 对照 [CsWinRT](https://github.com/microsoft/CsWinRT) 的 C# 投影确认语义——同一套投影模型，
   kotlin-winrt 行为与它不一致时以它为准（README Projection References 原话）。
4. 在 Windows 上构建验证：`runWinAppHostWinuiJvmMain` 走 JVM 先跑通，再跑 Native；
   packaged 才有的能力（通知、自启、后台任务）用 `runWinAppPackage*` 验证。

## 与 compose-fluent-ui 的分工

- 长得像 Fluent 的跨平台界面 → compose-fluent。
- 真 Mica/窗口材质、通知、选择器、剪贴板等系统行为 → kotlin-winrt 投影。
- 两者 overlapping 的只有"控件长相"，行为层不重叠，不用二选一。
