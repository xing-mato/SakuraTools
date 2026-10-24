# Changelog

## 1.1.4
- 插件 id 改为自有命名空间 `sakuratools.files`（原 `sakura.files` 借用官方前缀，可能与官方插件冲突）。
- 源码目录、zip 根目录、发布产物名同步为 `sakuratools.files`。
- **升级需先卸载旧 id 插件再安装**；插件设置会重置。
- 自检与打包脚本会把 stdout 切到 UTF-8，并在 CI 里设置 `PYTHONUTF8=1`；此前在 cp1252 控制台直接 `UnicodeEncodeError`。

## 1.1.3
- 修复：工具注册分组从 `files` 改为 `plugin`。此前工具注册成功但不在 Agent 的可见分组里，模型看不到任何文件工具。

## 1.1.2
- 插件改名为 **SakuraTools**（设置页标题同步）。

## 1.1.1
- 作者改为 mato；描述覆盖「默认只读 / 可开完全权限」。

## 1.1.0
- 设置页重构：可访问范围（用户目录 / 桌面 / 文档 / 下载 / 图片 / 全部磁盘 / 自定义目录）、文件数量上限（自定义或不限）、写入权限（只读 / 完全权限）。
- 移除界面上的单文件大小、返回字符数、隐藏文件、禁止文件四项；改为内置硬顶。
- 新增 `files__write`、`files__mkdir`、`files__move`（仅完全权限）。

## 1.0.0
- 首个版本：`files__list` / `files__read` / `files__read_image` / `files__stat` / `files__find` / `files__grep`。
- 图片经宿主 Artifacts 进入本轮对话，等同于用户手动截图。
- 支持 docx/xlsx/pptx/odt/ods/epub/html/rtf/pdf（含中文 ToUnicode）与纯文本编码探测。
