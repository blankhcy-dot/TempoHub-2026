# TempoHub NetEase Lyrics

让 EDIFIER TempoHub / Halo PixelBar 显示网易云歌词、系统音频频谱、消息通知和游戏性能曲线。

这是一个面向已经购买设备并安装了官方 TempoHub 的用户的非官方增强工具。
仓库不包含 EDIFIER 的原程序或资源文件；安装器只在用户本机读取官方安装，
生成一个独立的歌词补丁副本。安装过程不会修改官方安装目录。

## 功能

- 网易云桌面客户端播放时自动搜索、匹配并获取同步歌词。
- 优先读取网易云客户端当前歌曲的 `trackId`，直接获取歌词，避免搜索接口频繁触发限流。
- 使用歌曲标题、歌手、专辑和时长评分，降低 Live、Remix、伴奏、翻唱版本的误匹配。
- 直接读取网易云播放器的当前时间，拖动进度条后歌词立即重新定位。
- 启动补丁版 TempoHub 时，如果网易云音乐尚未运行，会自动拉起客户端并开启精确同步端口。
- 如果网易云已经运行但没有开启 `9222` 同步端口，插件会自动重启网易云一次以恢复歌词。
- 原生歌词模式下自动保持设备歌词屏开启。
- 支持 `-5 秒 ~ +5 秒` 歌词偏移，横向滑杆调整后自动应用。
- 网易云歌词不可用时回退到 TempoHub 原有的 QQ 音乐歌词逻辑。
- 左侧场景导航可在歌词、音频频谱、消息通知和游戏性能之间切换。
- 音频频谱使用 Windows WASAPI 系统输出回环，支持柱状频谱、波形和双 VU 表。
- 消息通知支持微信、QQ 和 QQ 邮箱；优先使用 Windows 通知中心，并回退到未读窗口标题检测。
- 游戏性能页显示 FPS、CPU、GPU、GPU 温度、内存及四条历史曲线。
- 音效调优页可直接切换设备硬件 Music / Game / Movie 模式，并说明各模式的听感取向。

## 安装

### 方式一：Release 安装器

1. 安装并登录官方 EDIFIER TempoHub，至少启动过一次设备。
2. 从本仓库的 Releases 下载 `TempoHub-NetEase-Installer.exe`。
3. 运行安装器。安装器会关闭正在运行的 TempoHub，并在
   `%LOCALAPPDATA%\TempoHubNetEase` 生成补丁副本。
4. 使用桌面的 **EDIFIER TempoHub - 网易云歌词** 启动。
5. 首次启动时，如果网易云已经在运行，启动器会询问是否重启一次网易云。
   重启只是为了开启本机 `127.0.0.1:9222` 的精确进度接口。

设置面板在桌面的 **EDIFIER TempoHub - 歌词显示设置**。如果 TempoHub
或网易云音乐尚未运行，设置快捷方式会自动启动它们。

### 方式二：从源码安装

需要 Windows、Python 3.10+，以及 `pip install pyinstaller`。

```powershell
git clone <repo-url>
cd TempoHub-NetEase-Lyrics
python installer.py
```

安装器会自动下载 Python 3.9 运行库。它还需要官方 TempoHub 已经安装。

如果自动查找失败：

```powershell
python installer.py --app-dir "C:\Program Files (x86)\EDIFIER TempoHub"
```

## 使用说明

- 直接启动 **EDIFIER TempoHub - 网易云歌词**，网易云音乐未运行时会自动启动。
- 启动 **EDIFIER TempoHub - 歌词显示设置** 时，也会自动拉起 TempoHub 和网易云音乐。
- 如果设置面板提示“网易云精确同步端口 9222 未开启”，请关闭网易云，
  再从歌词快捷方式启动一次。
- 日志位于 `%TEMP%\tempo_hub_netease_lyrics.log`。
- 设置保存在 `%APPDATA%\TempoHubLyrics\settings.json`。
- FPS 由随安装包提供的 Intel PresentMon 采集，首次启用需要一次 Windows 管理员授权。
- CPU 温度取决于主板驱动权限；无法读取时会显示 `--`，其他性能指标不受影响。
- Halo PixelBar 当前固件只开放三个硬件 EQ 预设，不响应自定义频段 EQ 查询，
  因此控制台不会提供无效的自定义均衡器滑杆。

## 卸载

运行 `%LOCALAPPDATA%\TempoHubNetEase\uninstall.ps1`。卸载器只移除补丁副本、
运行库和桌面快捷方式，不修改官方 TempoHub。

## 实现原理

TempoHub 使用 PyInstaller 和 Python 3.9 打包。安装器会：

1. 从用户自己的 `EDIFIER TempoHub.exe` 读取嵌入的 `PYZ.pyz`。
2. 保留所有原始模块，只替换 `app.utils.pixel_lyrics_util`。
3. 将原模块保留为 `app.utils.pixel_lyrics_util_orig` 供回退使用。
4. 生成新的 EXE，并通过 `_internal` 目录连接复用官方资源。
5. 通过网易云的本机调试端口读取播放器当前时间，通过本地 HTTP API 将
   设置和歌词状态提供给设置面板。

第三方组件和许可证说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 兼容性

当前版本按 2026-10-21 更新的官方 TempoHub Python 3.9 / PyInstaller 布局验证。
官方客户端更新后，模块路径或打包结构可能变化；如果安装器提示不兼容，
请提交 Issue 并附上 TempoHub 版本号和安装器错误输出。

## 免责声明

本项目是非官方社区工具，与 EDIFIER、花再、网易云音乐均无关联。使用者应
自行拥有合法安装的 TempoHub 和网易云音乐客户端。请遵守当地法律、软件许可
和音乐服务条款，不要将本工具用于绕过付费、版权保护或账号限制。
