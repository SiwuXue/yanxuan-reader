# yanxuan-reader · 盐选书房

把知乎网页中可阅读的文章与盐选章节保存为 EPUB、TXT 或 Markdown，方便离线阅读和导入墨水屏设备。

[下载最新版](https://github.com/SiwuXue/yanxuan-reader/releases/latest) · [更新日志](CHANGELOG.md) · [构建状态](https://github.com/SiwuXue/yanxuan-reader/actions) · [反馈问题](https://github.com/SiwuXue/yanxuan-reader/issues)

## 下载与启动

当前发布版本：**v5.0.2**。发布包包含 Python 运行环境、Web 界面和字体 OCR 模型，无需另行安装 Python。

| 平台 | 下载 |
| --- | --- |
| Windows x64 | [zhihu-downloader-5.0.2-windows-x64.exe](https://github.com/SiwuXue/yanxuan-reader/releases/download/v5.0.2/zhihu-downloader-5.0.2-windows-x64.exe) |
| macOS Apple Silicon（M 系列） | [zhihu-downloader-5.0.2-macos-arm64](https://github.com/SiwuXue/yanxuan-reader/releases/download/v5.0.2/zhihu-downloader-5.0.2-macos-arm64) |
| Linux x64 | [zhihu-downloader-5.0.2-linux-x64](https://github.com/SiwuXue/yanxuan-reader/releases/download/v5.0.2/zhihu-downloader-5.0.2-linux-x64) |

Windows 下载 `.exe` 后双击启动。程序会打开浏览器，默认地址为 `http://127.0.0.1:3000/`；端口被占用时会尝试后续端口，以启动日志显示的地址为准。使用期间保持程序运行，关闭浏览器标签不会停止后台服务。

macOS 和 Linux 在下载目录打开终端，赋予执行权限后启动。例如 Linux：

```bash
chmod +x zhihu-downloader-5.0.2-linux-x64
./zhihu-downloader-5.0.2-linux-x64
```

macOS 将文件名换成 `zhihu-downloader-5.0.2-macos-arm64`。当前未提供 Intel Mac 预构建包，可使用下方的源码运行方式。Linux 发布包在 Ubuntu 22.04 上构建。

发布包暂未代码签名；系统可能显示来源或签名提示。文件完整性可对照 Release 附件 [SHA256SUMS.txt](https://github.com/SiwuXue/yanxuan-reader/releases/download/v5.0.2/SHA256SUMS.txt) 检查。

## 三步开始使用

1. **登录**：点击右上角“扫码登录”，用知乎 App 扫码并确认；也可以点击登录状态入口，手动导入 Cookie。
2. **下载**：粘贴章节或专栏目录链接，选择 EPUB、TXT 或 Markdown，开始下载。
3. **阅读**：任务完成后下载导出文件。书籍会加入本地书架，可检查更新、补充新章节。

单章节链接只下载该章节；需要整本时，请提供专栏目录链接。仅用于备份本人有权访问的内容，付费正文仍需账号具有相应阅读权限。

## 功能

- **字体解码**：识别页面内嵌字体，按实际字体分别还原字符，必要时通过字形 OCR 解码。
- **三种导出格式**：EPUB 适合阅读器，TXT 便于纯文本阅读，Markdown 保留结构。
- **断点续传**：保留已完成章节，中断后再次下载同一链接可继续。
- **本地书架**：管理下载记录，检查并下载新增章节。
- **多种登录方式**：扫码登录，或导入 JSON、Netscape cookies.txt、原始 Cookie 字符串。
- **命令行操作**：支持批量链接、输出目录、限速和环境诊断。

### v5.0.1 字体修复说明

本版修复了字形名称与乱码字符相同时跳过 OCR，以及多套字体映射混用的问题。解码按正文使用的字体作用于文本，保留 HTML 属性和脚本。

**升级不会自动修复旧文件。** 如果之前下载过乱码正文，请取消勾选“断点续传”后重新下载；命令行使用 `--no-resume`。否则可能继续复用旧缓存。OCR 仍可能出现个别错字，不能保证所有页面都能完整还原。

## 支持的链接

下表中的 ID 为占位符，使用时替换成实际链接。

| 内容 | 链接形式 | 处理方式 |
| --- | --- | --- |
| 盐选专栏目录 | `https://www.zhihu.com/market/paid_column/<专栏ID>` | 获取目录并逐章下载 |
| 盐选单章节 | `https://www.zhihu.com/market/paid_column/<专栏ID>/section/<章节ID>` | 下载指定章节 |
| 知乎公开回答 | `https://www.zhihu.com/question/<问题ID>/answer/<回答ID>` | 按单篇正文下载 |
| 知乎专栏文章 | `https://zhuanlan.zhihu.com/p/<文章ID>` | 按单篇正文下载 |

当前无法直接下载 `story.zhihu.com` 的仅 App 阅读内容。如果同一内容存在可阅读的 `www.zhihu.com/market/paid_column/…` 网页版，请使用该网页版链接。仅修改链接不能获得额外阅读权限。

## 本地数据

Web 界面的默认数据目录位于用户主目录下的 `.zhihu_downloader`：

```text
.zhihu_downloader/
├── cookies.json     # 登录信息
├── shelf.json       # 书架记录
└── output/          # 导出文件与任务缓存
```

Windows 对应 `%USERPROFILE%\.zhihu_downloader`，macOS/Linux 对应 `~/.zhihu_downloader`。命令行下载默认输出到当前工作目录的 `output/`，也可用 `-o` 指定路径。

## 从源码运行

需要 **Python 3.10+**，推荐使用与发布构建一致的 Python 3.12。前端为原生 HTML/CSS/JavaScript，无需 Node.js 或 Rust。

```bash
git clone https://github.com/SiwuXue/yanxuan-reader.git
cd yanxuan-reader
python -m venv .venv
```

激活虚拟环境：

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

安装依赖并启动：

```bash
python -m pip install -e .
python -m zhihu_downloader gui
```

项目仓库名是 `yanxuan-reader`，Python 模块名仍为 `zhihu_downloader`，安装后的命令名为 `zhihu-downloader`。

### 常用命令

```bash
# 扫码登录
zhihu-downloader login

# 下载并导出 EPUB；将 URL 替换成实际链接
zhihu-downloader download --url "URL" -f epub -o ./output

# 忽略旧缓存，重新下载并解码
zhihu-downloader download --url "URL" -f epub --no-resume

# 批量下载：urls.txt 每行一个链接
zhihu-downloader download --batch-file urls.txt -f epub

# 查看书架、检查全部书籍的更新
zhihu-downloader shelf list
zhihu-downloader shelf update --all

# 检查登录、网络及运行环境
zhihu-downloader doctor

# 指定端口启动 Web 界面
zhihu-downloader gui --port 3001
```

从本机浏览器导入 Cookie 是可选功能，需要额外安装依赖：

```bash
python -m pip install -e ".[browser]"
zhihu-downloader login --browser
```

## 常见问题

**下载完成但正文仍然错乱**

确认使用 v5.0.1 或更新版本，取消“断点续传”后重新下载，并打开新生成的文件。若仍有错误，请在 Issues 中提供版本号、链接类型、错误信息和局部对照，不要附带 Cookie。

**Cookie 保存失败或出现“拒绝访问”**

确认 `.zhihu_downloader` 目录可以写入，并用当前用户重新启动程序。若服务由受限环境启动，也需要检查该进程的访问权限；重新扫码不会修复目录权限。

**登录失效或请求被拒绝**

重新扫码或导入有效 Cookie，并确认同一账号能在网页中阅读目标内容。持续失败时运行 `zhihu-downloader doctor` 查看诊断信息。

**下载后只得到部分内容**

先确认提供的是单章节还是整本目录链接，并检查网页端实际可读范围。工具只能处理服务器返回的内容。

## 开发与发布

主要目录：

```text
src/zhihu_downloader/
├── app/             # FastAPI 服务与静态 Web 界面
├── auth/            # 扫码登录、Cookie 与诊断
├── engine/          # 请求、下载编排与断点缓存
├── parse/           # 正文解析、清洗与字体解码
├── export/          # TXT / Markdown / EPUB 导出
├── shelf/           # 本地书架
├── cli.py           # 命令行入口
└── update.py        # 新版本检查
packaging/           # PyInstaller 打包配置
tests/               # 自动化测试
.github/workflows/   # CI 与发布流水线
```

安装开发依赖并检查：

```bash
python -m pip install -e ".[dev]"
ruff check src tests
python -m pytest -q
```

部分文件权限测试依赖 POSIX 权限语义，在 Windows 上可能失败；云端 CI 在 Linux 上执行完整测试。

### GitHub Actions 自动发布

推送到 `master`/`main` 或提交相关 PR 时，[CI](.github/workflows/ci.yml) 会运行 Python 3.10、3.12 的代码检查和测试。[发布流水线](.github/workflows/release.yml) 由 `v*` 标签触发。

发布新版本时：

1. 同步修改 `pyproject.toml` 的版本号、`src/zhihu_downloader/__init__.py` 的 `__version__`，在 `CHANGELOG.md` 添加对应版本段，并更新 README 下载链接。
2. 运行 `python scripts/check_release.py --tag vX.Y.Z`，将占位版本替换为实际版本。
3. 提交修改、推送分支，再创建并推送同名标签：

```bash
git add pyproject.toml src/zhihu_downloader/__init__.py CHANGELOG.md README.md
git commit -m "release: prepare vX.Y.Z"
git push origin master
git tag vX.Y.Z
git push origin vX.Y.Z
```

Action 会依次执行版本校验、全量测试、三平台构建、可执行文件启动检查，最后生成 `SHA256SUMS.txt` 并创建 GitHub Release。只有全部构建成功才发布；可在 [Actions 页面](https://github.com/SiwuXue/yanxuan-reader/actions) 查看进度。

## 致谢与许可证

基于 [xfengyin/zhihu-salt-novel-downloader](https://github.com/xfengyin/zhihu-salt-novel-downloader) 开发，保留原有提交历史和版权声明。字体 OCR 解码思路参考 [moran69/yanxuan](https://github.com/moran69/yanxuan)。

使用 [MIT License](LICENSE)。
