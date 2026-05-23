# NAStool 更新文档（CHANGELOG）

> 本文档自 v3.4.x 起改为**静态导航页**。
> 各版本明细不再写入本文件，统一存放在 [`docs/changelog/`](./changelog/) 目录下，每个 tag 一个文件。

## 在哪里看版本变更？

| 渠道 | 用途 |
|------|------|
| [GitHub Releases](https://github.com/joneezhu/NasTools/releases) | 对外发布页面（含二进制 assets + 聚合 changelog） |
| [`docs/changelog/`](./changelog/) | 本仓库内的单 tag 单文件 changelog（GitHub Release body 的源数据） |
| `git tag -n9 vX.Y.Z` | 命令行查看 annotated tag message（精简版） |

## 为什么改成单 tag 单文件？

历史上 `CHANGELOG.md` 是个不断追加的总账文件，每次发版都在顶部插入新节。这种模式有以下问题：

- 文件越长，diff 越大，code review 噪音越多
- GitHub Release body 需要的数据形态和总账文件不一致，要写两份
- 多个 tag 之间的合并发布（中间漏建 Release）很难拼接

自 v3.4.x 起改为：

1. **`scripts/release.sh`** 只写 `docs/changelog/<tag>.md`，不再修改本文件
2. **`scripts/release-github.sh`** 直接读 `docs/changelog/<tag>.md` 作为 GitHub Release body，必要时聚合多 tag
3. 本文件仅作导览，**禁止再追加版本节**

## 变更类别说明

每个 `docs/changelog/<tag>.md` 都按下列分类组织（与 [Keep a Changelog 1.1.0](https://keepachangelog.com/zh-CN/1.1.0/) 对齐）：

| 类别 | 含义 |
|------|------|
| **Added** | 新增功能 / 文件 / 接口 / 插件 |
| **Changed** | 既有行为或界面的非破坏性调整 |
| **Fixed** | Bug 修复 |
| **Removed** | 已删除的功能 / 文件 / 接口 |
| **Security** | 安全相关修复 |
| **Deprecated** | 废弃但暂未移除（标注移除计划） |
| **Breaking** | 破坏性变更（用户必须主动适配） |

## 编写规范

`release.sh` 自动从 commit subject 解析分类（基于 conventional commits 前缀：`feat:` / `fix:` / `refactor:` 等）。如果想手工组织条目，可遵循以下原则：

- 优先附 Issue / PR 编号：`(#123)` —— `release.sh` 会自动 linkify
- 重大变更附 commit hash：`(abc1234)` —— `release.sh` 会自动转成 GitHub commit 链接
- 破坏性变更必须给出 **迁移指引**
- 主语统一为「NAStool」或具体模块名，避免出现「我」「我们」
- 描述用现在式或完成时，避免「将会」「拟」「即将」之类不确定表述
- 一行一个变更点，禁止多个变更挤在一行

## 与其他文档的关系

- **CHANGELOG.md**（本文）：**导航页**，告诉读者去哪里找版本明细
- **`docs/changelog/<tag>.md`**：**变更明细**，每个 tag 一份，对外公开
- **RELEASE.md**：**发布流程与规范**，面向维护者
- **USAGE.md**：**使用文档**，面向最终用户

四份文档协同，构成 NAStool 的对外文档体系。
