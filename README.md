# TempoHub 网易云歌词

为已安装官方 EDIFIER TempoHub 的 Halo PixelBar 用户提供独立补丁副本，不修改官方安装目录。

## 本地精简版

控制台仅保留两个页面：

- **歌词同步**：网易云当前歌曲匹配、精确进度、歌词偏移和原生歌词显示。
- **音效调优**：切换硬件 Music / Game / Movie 预设。

无法实时同步的消息通知、游戏性能、自定义频谱预览和原生频谱律动已移除，相关导航、设置和设备指令已删除。
TempoHub 原有 QQ 音乐歌词逻辑继续使用。窗口保留一体化圆角、红黄绿按钮、拖动、缩放和关闭前保存。

当前版本 **v1.0.8**。可从 [最新 Release](https://github.com/blankhcy-dot/TempoHub-2026/releases/latest)
下载 `TempoHub-NetEase-Installer.exe`。安装包自带运行库，无需另装 Python；仍需先安装官方 EDIFIER TempoHub。

## 使用

打开桌面快捷方式 **EDIFIER TempoHub - 歌词显示设置**，控制台会启动补丁版 TempoHub。
如果 TempoHub 已随系统在后台启动，打开控制台也会唤起它的主界面，完成设备初始化。
右上角按钮从左到右为：最小化、最大化、关闭。
本地更新后重新打开控制台，以载入新的页面代码。

歌词偏移范围为 -5 秒到 +5 秒：正值提前、负值延后。
设置保存在 `%APPDATA%\TempoHubLyrics\settings.json`，日志位于 `%TEMP%\tempo_hub_netease_lyrics.log`。

## 安装与构建

需要 Windows 和已安装的官方 EDIFIER TempoHub。使用 Python 3.10+ 运行 `installer.py` 从源码安装。
安装器在本机读取官方 EXE，保留原始模块并加入歌词适配及原生显示控制。
原歌词模块以 `app.utils.pixel_lyrics_util_orig` 保留用于回退，不分发官方程序或官方资源。

使用 `./build_release.ps1 -Python python` 构建安装包，脚本会用 Python 3.9 编译补丁字节码。
GitHub Actions 只在手动触发或版本标签推送时打包，不自动运行测试。
卸载时运行补丁目录内的 `uninstall.ps1`。

第三方组件说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
本项目与 EDIFIER、花再和网易云音乐无关联，请遵守相关服务条款与软件许可。
