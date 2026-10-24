# SakuraTools

给 [Sakura](https://github.com/Rvosy/sakura) 加一双“眼睛和手”：让她自己打开你电脑上的文件，而不是等你把内容贴进聊天框。

- **文档**：docx / xlsx / pptx / odt / ods / odp / pdf / epub / html / rtf / 纯文本、代码、日志
- **图片**：png / jpeg / webp / gif —— 读进**本轮对话**，模型能真的看见画面
- **默认只读**：只有在你把“写入权限”改成“完全权限”之后，才会出现写入类操作

## 它补的是哪个缺口

Sakura 本来就能看图：你手动截图发给它，视觉通道就工作。
但它没法**自己**去磁盘上取一张图 —— “把我桌面那张截图看一下”只能靠人喂。

这个插件把这条路接通了：工具把图片字节写进宿主的 Artifacts 目录并 commit，
返回 `{"content": "...", "artifact": {...}}`，宿主随后把它当作
`data:image/...` 附件放进本轮消息 —— 与手动发送截图同一条视觉通道。

## 安装

两种方式任选：

1. **插件市场**（若已收录）：设置 → 插件 → 市场 → SakuraTools → 安装
2. **从 ZIP 安装**：下载 Release 里的 `sakuratools.files-<version>.zip` → 设置 → 插件 → 从 ZIP 安装

装完重启 Sakura，插件列表里会出现“SakuraTools”。

升级：先卸载同名插件再装，否则会被 `PLUGIN_ID_CONFLICT` 拒绝。

## 设置项

| 项 | 取值 | 说明 |
|---|---|---|
| 可访问范围 | 用户目录 / 桌面 / 文档 / 下载 / 图片 / **全部磁盘** / 自定义目录 | 选“全部磁盘”可读所有固定磁盘（跳光驱、U 盘、网络盘） |
| 自定义目录 | 每行一个路径 | 仅当范围选“自定义目录”时出现 |
| 文件数量上限 | 自定义 / **不限（有风险）** | 一次最多能列出/搜索到多少个文件；选“不限”可能一次返回上千个 |
| 最多文件数 | 1–500，默认 50 | 仅当上面选“自定义”时出现 |
| 写入权限 | **只读**（默认） / 完全权限 | 完全权限额外允许新建目录、写入/覆盖、移动文件 |

“全部磁盘 + 不限条数 + 完全权限”这类组合会让状态栏变成警告色，并在工具日志里留痕。

## 工具

| 工具 | 权限 | 作用 |
|---|---|---|
| `files__list` | 只读 | 列目录，带大小/时间/图片尺寸 |
| `files__read` | 只读 | 读正文：文本带行号，Office/PDF 自动抽正文 |
| `files__read_image` | 只读 | 把图片送进本轮对话（视觉） |
| `files__stat` | 只读 | 属性：类型、大小、时间、图片尺寸、sha256 |
| `files__find` | 只读 | 按文件名找 |
| `files__grep` | 只读 | 目录内文本搜索 |
| `files__write` | 完全权限 | 写入/追加文本文件 |
| `files__mkdir` | 完全权限 | 新建目录 |
| `files__move` | 完全权限 | 移动或重命名 |

只读模式下调用写入类工具会直接返回 `FILES_READ_ONLY`，并提示去设置里改权限。
**没有删除工具** —— 要删文件请自己在资源管理器里做。

## 格式支持与限制

- **PDF**：自研最小抽取器，处理 Flate 内容流与 ToUnicode/Identity-H 的中文正文；
  扫描件取不到文字，会明确说明。
- **不支持**：旧版二进制 `doc/xls/ppt`、加密文档 → `FILES_UNSUPPORTED`。
- **图片**：只解析文件头，不解码不缩放；大图会消耗大量视觉 token。
- **没有 OCR**：模型是“看图”，不是“读字”。

## 安全模型

1. **范围白名单**：路径先 `realpath` 解析（含 junction/symlink），再判断是否在范围内 → 越界 `FILES_OUTSIDE_ROOT`。
2. **敏感路径黑名单（不可关闭）**：`.ssh`、`.gnupg`、`.aws`、Windows 凭据库、浏览器配置目录、`*.pem/*.key/*.pfx/*.kdbx` 等。
3. **内置硬顶**：单文件 48 MB、单次返回 2 万字符、遍历 2 万条目、grep 扫 5000 个文件。
   这些不暴露在界面上，防止一次调用把进程拖死。
4. **写入默认关闭**，且写入同样受范围与黑名单约束。

## 自检

```powershell
python selftest.py
```

44 项断言：文本/GBK/Office/PDF（含中文 ToUnicode）/HTML、图片工件、越界与敏感拒绝、
只读拒绝写入、完全权限下写入/追加/建目录/移动、条数上限与不限模式、设置页读写与状态。
临时文件放在插件目录的 `.selftest-tmp`，跑完自动清理。

## 目录结构

仓库根目录就是插件本体——插件市场会直接抓取仓库源码打包，因此 `plugin.yaml` 必须在根目录，
且不能有任何嵌套的 `plugin.yaml`。

```
.
├── plugin.yaml          清单（api 4）
├── plugin.py            入口：注册 9 个工具与设置页
├── files_core/
│   ├── handlers.py      工具实现（含写入工具与图片信封）
│   ├── policy.py        范围白名单 + 敏感路径
│   ├── config.py        范围/条数/权限 与设置描述符
│   ├── textio.py        文本读取（行号/截断）
│   ├── decode.py        编码探测（UTF-8/GB18030/Big5）
│   ├── documents.py     Office/ODF/EPUB/HTML/RTF
│   ├── pdf.py           PDF 文本抽取
│   └── images.py        图片头解析与工件
├── selftest.py          离线自检（44 项）
├── build_sakura_files.py 打包脚本：生成可安装的 zip
└── .github/workflows/   CI 与自动发版
```

重新打包（在仓库根目录）：

```powershell
python build_sakura_files.py
```


## 开发

```powershell
# 自检（44 项断言，临时文件写在 .selftest-tmp，跑完自动清理）
python selftest.py

# 打包：生成 sakuratools.files-<version>.zip
python build_sakura_files.py
```

纯标准库实现，无需安装依赖。发版流程：改 `plugin.yaml` 的 `version` → commit →
`git tag -a vX.Y.Z` → push tag，GitHub Actions 会自动跑自检、打包并发布 Release
（含 `SHA256SUMS`）。

## 许可

MIT。Sakura 本身同样以 MIT 发布。
