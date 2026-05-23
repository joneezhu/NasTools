# NAStool 更新文档（CHANGELOG）

> 文档编写：2026-05-18
> 当前最新版本：**v3.4.1**
> 版本号规范：见 `RELEASE.md` 第一节

本文档遵循 [Keep a Changelog 1.1.0](https://keepachangelog.com/zh-CN/1.1.0/) 风格。每次发布必须在顶部新增一节，按 **Added / Changed / Fixed / Removed / Security / Deprecated** 分类列出变更。

---

## 变更类别说明

| 类别 | 含义 |
|------|------|
| **Added** | 新增功能 / 文件 / 接口 / 插件 |
| **Changed** | 既有行为或界面的非破坏性调整 |
| **Fixed** | Bug 修复 |
| **Removed** | 已删除的功能 / 文件 / 接口 |
| **Security** | 安全相关修复 |
| **Deprecated** | 废弃但暂未移除（标注移除计划） |
| **Breaking** | 破坏性变更（用户必须主动适配） |

---

## [Unreleased]

> 下一版本开发中尚未发布的变更。

### Added
- _（待补充）_

### Changed
- _（待补充）_

### Fixed
- _（待补充）_

---

## [v3.4.1] - 2026-05-18

> 文档化与稳定性维护版本。新增三份独立的项目文档（USAGE / RELEASE / CHANGELOG），并对启动链路、文件资源管理、异常捕获等若干历史隐患进行修复。

### Added
- **`PROJECT_REPORT.md`**：完整的项目分析报告（架构、模块、规模、Bug 清单与改进建议）
- **`docs/USAGE.md`**：使用文档（部署、配置、核心功能指引、FAQ）
- **`docs/RELEASE.md`**：发布文档（版本规范、流程、产物、回滚、检查清单）
- **`docs/CHANGELOG.md`**：本更新文档

### Fixed
- **`initializer.py:37`** —— 日志 f-string 缺前缀：
  - 修复前：`log.info("日志将上送到服务器：{logserver}")`
  - 修复后：`log.info(f"日志将上送到服务器：{logserver}")`
  - 影响：之前日志会原样打印 `{logserver}` 而非实际地址，难以定位日志服务配置问题
- **`run.py:72-73`** —— 删除重复的 `_ssl_key = app_conf.get('ssl_key')` 赋值（赘余代码，无功能影响）
- **`app/utils/torrent.py:163`** —— 文件资源泄漏：
  - 修复前：`bdecode(open(path, 'rb').read())`
  - 修复后：使用 `with open(path, 'rb') as f:` 上下文管理
  - 影响：高频调用场景下可能耗尽文件描述符
- **`app/utils/torrent.py:420`** / **`app/filetransfer.py:1249`** / **`web/main.py:1825`** ——
  bare `except:` 改为 `except Exception:`，避免吞没 `KeyboardInterrupt` / `SystemExit`，符合 PEP 8

### Changed
- 不涉及

### Removed
- 不涉及

### Security
- 不涉及

### 已知问题（待评估，未在本版本修改）
- `app/plugins/modules/cookiecloud.py:390-393` —— `re.search` 结果未做 `None` 校验
- `app/helper/downloader_helper.py` —— 多处 `== True` / `!= None`（PEP 8 不规范）
- `app/media/tmdb.py:94` —— 混合类型比较
- `app/plugins/modules/_autosignin/sites/*.py` —— `type(x) == y` 应改为 `isinstance()`
- `web/action.py` 5388 行巨文件，建议按业务域拆分
- `tests/` 仅 7 个测试文件，单元测试覆盖率严重不足

---

## [v3.4.0] - 2025（历史，需按 Git 历史回填）

> 本节为占位说明：v3.4.0 及以前的版本由项目长期维护中累积，建议在后续发布中通过 `git log` 回填关键变更。下面列出 README 中已声明的、相对于官方 3.2.3 的累计变更：

### Added
- 支持 Aria2 / 115 / PikPak 下载器
- 支持 Chromedriver 114+ 的 Google 浏览器
- 支持识别历史记录一键清理
- 支持通过插件安装 Jackett / Prowlarr 扩展内置索引
- 支持 TMDB 搜索 18+ 内容
- 支持开关控制刮削时是否抓取媒体实际信息
- 支持管理「我的媒体库」显示模块

### Fixed
- 修复豆瓣图片无法显示
- 修复豆瓣同步「近期动态」与「全量同步」失效
- 修复高清空间签到 Cookies 错误

### Changed
- 持续更新内置索引站点

---

## 历史版本提示

> v3.4.0 之前的详细变更请参阅：
> - GitHub Releases：<https://github.com/joneezhu/NasTools/releases>
> - 上游官方仓库（基础来源 v3.2.3）：<https://github.com/NAStool/nas-tools>

---

## 编写规范

### 撰写新版本条目

发布新版本时，将 `[Unreleased]` 章节内容下沉为正式版本，并在顶部新建空的 `[Unreleased]`。模板：

```markdown
## [vX.Y.Z] - YYYY-MM-DD

> 一句话总览本次发布主旨。

### Added
- 功能 A：简要说明 + 关联 Issue/PR 链接

### Changed
- 模块 B 重构：说明动机与对用户行为的影响

### Fixed
- `path/to/file:line` —— Bug 描述：根因 + 修复方案

### Breaking
- ⚠️ 配置项 `xxx` 已重命名为 `yyy`，请修改 `config.yaml`
```

### 链接与回溯

- 优先附 Issue / PR 编号：`(#123)`
- 重大变更附 commit hash：`(abc1234)`
- 破坏性变更必须给出 **迁移指引**

### 用语建议

- 主语统一为「NAStool」或具体模块名，避免出现「我」「我们」
- 描述用现在式或完成时，避免「将会」「拟」「即将」之类不确定表述
- 一行一个变更点，禁止多个变更挤在一行

---

## 与 RELEASE 文档的关系

- **CHANGELOG.md**（本文）：**变更明细的事实记录**，对外公开
- **RELEASE.md**：**发布流程与规范**，面向维护者
- **USAGE.md**：**使用文档**，面向最终用户

三份文档协同，构成 NAStool 的对外文档体系。
