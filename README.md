# SakuraTools

给 [Sakura](https://github.com/) 桌面宠物加一双“眼睛和手”：让它自己打开你电脑上的文件，而不是等你把内容贴进聊天框。

- 读文档：docx / xlsx / pptx / odt / ods / odp / pdf / epub / html / rtf / 纯文本与代码（自动识别 UTF-8 / GB18030 / Big5）
- 看图片：png / jpeg / webp / gif —— 直接进入本轮对话，模型真的能看见画面
- 找东西：按文件名搜索、在文本里检索、看属性
- 默认只读；需要时可在设置里开完全权限，允许写入 / 建目录 / 移动

## 安装

1. 下载 Release 里的 `sakuratools.files-<version>.zip`
2. Sakura → 设置 → 插件 → 从 ZIP 安装
3. 重启 Sakura

升级前先卸载同名插件，否则会报 `PLUGIN_ID_CONFLICT`。

## 文档

- 功能、设置项与限制：[sakuratools.files/README.md](sakuratools.files/README.md)
- 变更记录：[CHANGELOG.md](CHANGELOG.md)

## 开发

```powershell
# 自检（44 项断言，临时文件自动清理）
python sakuratools.files/selftest.py

# 打包：生成 sakuratools.files-<version>.zip
python build_sakura_files.py
```

纯标准库实现，无需安装依赖。

## 许可

MIT。Sakura 本身同样以 MIT 发布。
