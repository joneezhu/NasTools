# NAStool 发布文档（RELEASE）

> 适用版本：v3.4.1
> 文档编写：2026-05-18
> 适用范围：维护者 / 发布工程师 / 自建分发渠道用户

本文档定义了 NAStool 项目的 **版本号规范、发布流程、构建产物、回滚方案** 与 **后续发布检查清单**。日常使用请参考 `USAGE.md`，版本变更明细请参考 [`docs/changelog/`](./changelog/) 目录下的单 tag 文件。

---

## 一、版本号规范

NAStool 采用 [Semantic Versioning 2.0.0](https://semver.org/lang/zh-CN/) 风格，但实际维护以**主版本/次版本**为主：

```
v<MAJOR>.<MINOR>.<PATCH>
        │       │       │
        │       │       └── PATCH：Bug 修复 / 安全补丁，向下兼容
        │       └────────── MINOR：新增功能 / 重构，原则上向下兼容
        └────────────────── MAJOR：架构 / 协议级不兼容变更
```

- 版本号唯一来源：`version.py` 中的 `APP_VERSION`
- 当前版本：**v3.4.1**
- 维护分支：基于官方 `3.2.3` fork 演进
- 预发布标记：`vX.Y.Z-rc.N`（候选）/ `vX.Y.Z-beta.N`（公测）

---

## 二、发布渠道与产物

| 渠道 | 形态 | 触发方式 | 受众 |
|------|------|---------|------|
| Docker Hub | `joneezhu/NasTools:<tag>` | Tag 推送后 GitHub Actions 自动构建 | 主流用户 |
| GitHub Releases | 源码 zip / tar.gz、PyInstaller 可执行文件 | 手动发布 | 桌面用户、源码用户 |
| Git Tag | `vX.Y.Z` | 手动 `git tag` | 开发者 |

### 2.1 Docker 镜像 Tag 规则

| Tag | 含义 |
|------|------|
| `latest` | 最新稳定版（master 分支构建） |
| `vX.Y.Z` | 特定版本 |
| `beta` | 公测版（`debian-beta.Dockerfile` 构建） |
| `dev` | 开发版（`dev` 分支） |

### 2.2 PyInstaller 可执行文件命名

```
nastool_<platform>_v<version>[.exe]

示例：
  nastool_macos_v3.4.1
  nastool_linux_v3.4.1
  nastool_windows_v3.4.1.exe
```

---

## 三、发布前置条件

### 3.1 准入清单

- [ ] 所有 P0/P1 Bug 已修复并合并到 `master`
- [ ] `requirements.txt` 已锁定版本，且全部依赖在 PyPI 可正常拉取
- [ ] `package_list.txt` / `package_list_debian.txt` 已更新（如有系统包变更）
- [ ] `scripts/versions/` 下的 Alembic 迁移脚本已新增并自测
- [ ] `version.py` 的 `APP_VERSION` 已更新（如手动改；用 `release.sh` 时自动）
- [ ] `docs/changelog/<tag>.md` 已生成（`release.sh` 自动生成）
- [ ] `tests/` 全部通过（`python3 -m unittest discover tests`）
- [ ] 关键路径手工冒烟（启动、登录、订阅、识别、转移、下载器对接）
- [ ] Docker 镜像在 amd64 / arm64 双架构构建成功

### 3.2 兼容性评估

需在 CHANGELOG 显式声明的破坏性变更类别：

- 配置项变更（`config.yaml` 结构调整）—— 必须在 `initializer.update_config()` 中编写迁移逻辑
- 数据库 schema 变更 —— 必须新增 Alembic 版本脚本
- API 路由变更（`web/apiv1.py`）—— 老客户端需评估
- 插件 API 变更 —— 第三方插件适配评估

---

## 四、发布流程

### 4.1 主流程（图示）

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ 1. 代码冻结  │ -> │ 2. 版本号 +1 │ -> │ 3. 打 Tag    │ -> │ 4. 构建产物  │
│   freeze     │    │ + CHANGELOG  │    │   git tag    │    │  Docker/Bin  │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
                                                                    │
                                                                    ▼
                          ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
                          │ 7. 公告/通知 │ <- │ 6. 发布 GH    │ <- │ 5. 冒烟测试  │
                          │              │    │   Releases   │    │              │
                          └──────────────┘    └──────────────┘    └──────────────┘
```

### 4.2 一键发布脚本（推荐）

绝大多数发布无需手动执行下述七个步骤，使用 `scripts/release.sh` 即可一站式完成 **CHANGELOG 生成 + 版本号修改 + 打 Tag + 推送 + 触发构建**。

#### 前置依赖：安装 gh CLI

`scripts/release.sh` 通过 GitHub 官方 [`gh` CLI](https://cli.github.com/) 完成两件事：

1. 触发 `build.yml`（Docker Hub，含 stable / beta 两通道）与 `build-package.yml`（二进制 + GitHub Release）两条流水线
2. 调用 `gh release view` 判断目标 tag 是否已发布安装包（幂等行为依赖此能力）

未安装 `gh` 时脚本会拒绝执行，请按所在平台安装：

##### macOS

```bash
# 方式 1（推荐）: Homebrew
brew install gh

# 方式 2: 官方 pkg 安装包
# 到 https://github.com/cli/cli/releases/latest 下载对应架构 (arm64 / amd64) 的 .pkg
sudo installer -pkg ~/Downloads/gh_*_macOS_*.pkg -target /
```

##### Windows

```powershell
# 方式 1（推荐）: winget
winget install --id GitHub.cli

# 方式 2: Scoop
scoop install gh

# 方式 3: Chocolatey
choco install gh

# 方式 4: 官方 MSI 安装包
# 到 https://github.com/cli/cli/releases/latest 下载 gh_*_windows_amd64.msi 双击安装
```

> 安装后需重启终端（PowerShell / CMD / Windows Terminal）以让 PATH 生效。

##### Linux

```bash
# Debian / Ubuntu
sudo apt install gh

# 如果仓库版本太旧, 用官方 apt 源
type -p curl >/dev/null || sudo apt install curl -y
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
  | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
  | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update && sudo apt install gh -y

# Fedora / RHEL / CentOS
sudo dnf install gh

# Arch / Manjaro
sudo pacman -S github-cli
```

##### 验证安装

```bash
gh --version
# 期望输出: gh version 2.x.x ...
```

#### 前置依赖：gh CLI 登录授权

安装好之后必须登录，否则 `gh release view` / `gh workflow run` 都会被拒绝。两种方式任选其一：

##### 方式 A：交互式登录（推荐日常使用）

```bash
gh auth login
# 选 GitHub.com → HTTPS → Login with a web browser
# 浏览器自动打开授权, 完成后回到终端
```

##### 方式 B：用 `.release` 中的 RELEASE_GH_TOKEN 静默登录（推荐 CI / 多账号）

在 `.release` 中追加一行（让 `gh` 自动读环境变量、完全无交互）：

```bash
# .release
DOCKER_USERNAME=joneechu
DOCKER_PASSWORD=dckr_pat_xxx
RELEASE_GH_TOKEN=github_pat_xxx
GH_TOKEN=$RELEASE_GH_TOKEN          # 让 gh CLI 自动认证, 无需 gh auth login
```

或者一次性写入：

```bash
source .release
echo "$RELEASE_GH_TOKEN" | gh auth login --with-token
```

##### 验证登录态

```bash
gh auth status
# 期望: ✓ Logged in to github.com as <你的账号> ...

# 进一步验证有触发 workflow 的权限
gh workflow list -R joneezhu/NasTools
# 应能看到 build.yml / build-package.yml
```

> Token 权限要求：fine-grained PAT 需要 **Contents: Read and write** + **Actions: Read and write**；classic PAT 需要 `repo` + `workflow` scope。详见 token 章节。

#### 首次使用：配置凭据

```bash
cp .release.example .release
# 编辑 .release, 填入 DOCKER_USERNAME / DOCKER_PASSWORD / RELEASE_GH_TOKEN
```

`.release` 已加入 `.gitignore`，**不会被提交**。脚本启动时会自动加载，shell 中同名环境变量优先级更高（用于 CI 注入）。

#### 常用命令

```bash
# 演练（推荐先跑一次确认 CHANGELOG 内容）
scripts/release.sh v3.4.2 --dry-run

# 正式发布（默认 *不* 触发 CI，仅生成 commit/tag/changelog 并 push）
scripts/release.sh v3.4.2

# 发布并立刻触发 docker / package 流水线（ref 一律指向新 tag）
scripts/release.sh v3.4.2 --build

# 仅本地操作（不 push、不触发 CI，调试用）
scripts/release.sh v3.4.2 --no-push

# Tag message 不使用 emoji（兼容老旧 git 客户端）
scripts/release.sh v3.4.2 --no-emoji

# 调整 tag message 中变更条目上限（默认 12）
scripts/release.sh v3.4.2 --tag-limit=20
```

> **为什么默认不触发 CI**：避免误触发；同时给"先看 commit/tag 推上去是否正确"留出确认时间。需要触发时只要再跑一次 `scripts/release.sh <tag> --build`（脚本会进入"仅重跑打包"路径，只触发 build-package.yml）。
>
> **为什么 `--build` 用 tag 作 ref**：`gh workflow run --ref <tag>` 比 `--ref master` 更精确——`build-package.yml` 里 `softprops/action-gh-release@v1` 会把 Release 绑定到 ref 对应的 tag；用分支名时若分支后续有新 commit，ref 会漂移。

#### Tag message 格式

打出来的 annotated tag 内嵌结构化的变更摘要，例如：

```
Release v3.4.2
────────────────────────────────────────────────
Range  : v3.4.1 → v3.4.2
Date   : 2026-05-23
Commits: 18 kept / 22 total  ·  Categories: 3
────────────────────────────────────────────────

✨ Added  (5)
  • 支持站点签到自定义 URL 参数  (a1b2c3d)
  • ...

🐛 Fixed  (8)
  • 修复 brushtask 在断网时崩溃  (e4f5g6h)
  • ...

♻️ Changed  (5)
  • 提升 _autosignin 公共方法到基类  (i7j8k9l)
  • ...
```

可以在 GitHub Release 页、`git show v3.4.2`、`git tag -n99` 中直接查看，无需再翻 CHANGELOG。

脚本会：

1. 收集 **上一个 tag → HEAD** 的 commit，过滤噪声（merge / wip / typo / chore: lint 等），按前缀分类为 Added / Changed / Fixed / Removed / Breaking / Security / Deprecated
2. 同标题去重，自动剥离 `feat:` / `fix(scope):` 等约定式前缀
3. 把当次变更写入 `docs/changelog/<tag>.md`（**唯一的 changelog 落地点**，不再修改 `docs/CHANGELOG.md` 总账）
4. 修改 `version.py` 中的 `APP_VERSION`
5. 创建 `release: bump version to vX.Y.Z` commit，附带 5 条核心修改点
6. 打 annotated tag，tag message 内嵌结构化变更摘要（标题区 + 类目分组 + emoji 图标，默认上限 12 条，可用 `--tag-limit=N` 调整）
7. push master + tag 到远端
8. 通过 `gh workflow run` 触发 `build.yml`（Docker Hub，默认 channel=stable）与 `build-package.yml`（二进制 + Release）

#### 幂等行为（可重入）

脚本会先检查目标版本号在远端的状态，避免重复发布或漏发安装包：

| 场景 | tag 是否存在 | GitHub Release 安装包 | 行为 |
|------|------------|----------------------|------|
| A | ❌ 不存在 | — | 走完整流程（生成 changelog → 改 version → commit → tag → push → 触发 build.yml + build-package.yml 流水线） |
| B | ✅ 存在 | ✅ 至少 1 个 asset | 直接退出，提示 Release 链接（无事可做） |
| C | ✅ 存在 | ❌ 缺失 | 跳过 commit/tag/push，**仅基于已有 tag 重跑 `build-package.yml`** 出包 |

> 场景 C 的典型用例：tag 已打但打包流水线失败/被取消，重跑 `scripts/release.sh vX.Y.Z` 即可补出安装包，不会再生成新的 commit 或 tag。
>
> 场景 B/C 都需要本地 **gh CLI 已登录**（脚本会用 `gh release view` 判定 assets 数）。未登录时脚本会拒绝执行，避免误把"无权限"判定成"无安装包"导致重复发版。

#### 4.2.4 单 tag changelog 文件（`docs/changelog/<tag>.md`）

自 v3.4.x 起，**`docs/CHANGELOG.md` 不再被脚本写入**（只作为静态导览页保留）。每次 `release.sh` 把当前版本的变更**只**写入：

```
docs/changelog/<tag>.md      # 例如 docs/changelog/v3.4.3.md
```

文件结构：

```markdown
# Release v3.4.3

- **Date**: 2026-05-23
- **Range**: v3.4.2 → v3.4.3
- **Commits**: 5 kept / 7 total
- **Compare**: [v3.4.2...v3.4.3](https://github.com/<owner>/<repo>/compare/v3.4.2...v3.4.3)

---

## Added
- 新增 X 功能 ([#101](https://github.com/<owner>/<repo>/issues/101)) ([`abc1234`](https://github.com/<owner>/<repo>/commit/abc1234...))
...
```

**超链接自动生成**：脚本会从 `git remote.origin.url` 解析出 `owner/repo`，把 commit 短哈希链化为 commit URL，把正文里的 `#123` / `GH-123` 链化为 issue URL，并在文件头追加一条 `Compare` 链接（指向上一个 tag 到本 tag 的差异页）。git annotated tag message 仍保持纯文本（git 不渲染 markdown）。

它存在的目的：

1. **GitHub Release body 来源**：`scripts/release-github.sh` 直接把它作为 `--notes-file` 传给 `gh release create/edit`。
2. **可单独引用**：可在 issue / PR / 通告里链接到 `https://github.com/<owner>/<repo>/blob/master/docs/changelog/v3.4.3.md`。
3. **CI 友好**：未来若要把 release notes 推送到外部渠道（论坛 / Telegram / 邮件订阅），脚本可直接读这个文件。

文件由 `release.sh` 自动生成并随 `release: bump version to vX.Y.Z` 一起 commit & tag。**不要手动修改已发布版本的文件**；如要修订内容，应通过下面的 `release-github.sh` 重新刷 GitHub Release body 即可（仓库内的历史保留原版）。

#### 4.2.5 创建 / 更新 GitHub Release（`scripts/release-github.sh`）

`build-package.yml` 流水线在打包成功后会自动创建 Release **并上传 6 个平台的二进制 assets**，但**不再写 title/body**（自 v3.4.x 起的职责调整：CI 只管 assets，body 全权交给本地脚本）。`scripts/release-github.sh` 用于：

- **写入 / 替换 body**：把 Release 描述刷成 `docs/changelog/<tag>.md` 的标准格式（CI 创建出来时 body 是空的，需要本地脚本填）
- **首次创建**：CI 因故没建出 Release 时，本地直接 `create`
- **追加 assets**：上传额外文件（SHA256 校验、补丁包等），不冲掉原有 assets
- **预发布标记**：tag 含 `-beta.1` / `-rc.1` 等后缀时自动判定为 prerelease
- **聚合中间漏发的 changelog**：默认会从"上一个已发布的 GitHub Release"开始往后找，把这之间所有 tag 的 changelog 合并到本次 Release body（详见下方"Body 聚合策略"）

> **职责分工（重要）**
> - `build-package.yml` 的 `Create-release_Send-message` job：只 `tag_name + files`，不写 `name` 和 `body`，避免覆盖本地脚本写入的内容
> - `scripts/release-github.sh`：默认走 `gh release edit --notes-file`，只刷 title/body，**保留 CI 上传的 assets**
> - `--force-recreate` 会先 delete + create，**会丢掉 assets**，需要重跑 build-package.yml 补回（对应下面的幂等场景 C）

##### 用法

```bash
# 1) 最常见：基于 docs/changelog/v3.4.3.md 创建/更新 Release
scripts/release-github.sh v3.4.3

# 2) 预演不执行（推荐先跑一次确认聚合范围与内容）
scripts/release-github.sh v3.4.3 --dry-run

# 3) 创建为 draft (人工 review 后再发布)
scripts/release-github.sh v3.4.3 --draft

# 4) 标记为预发布 (tag 带后缀时自动开启)
scripts/release-github.sh v3.5.0-beta.1 --prerelease

# 5) 上传额外 asset (SHA256 / 补丁等), 用 , 分隔
scripts/release-github.sh v3.4.3 --assets=releases/SHA256SUMS.txt,releases/notes.pdf

# 6) 强制重建 Release (会丢失原有 assets, 谨慎使用)
scripts/release-github.sh v3.4.3 --force-recreate

# 7) 仅用当前 tag 自身的 changelog (不聚合中间漏发的 tag)
scripts/release-github.sh v3.4.3 --single

# 8) 强制指定起点 tag, 聚合 (since, tag] 区间
scripts/release-github.sh v3.4.5 --since=v3.4.2
```

##### 行为说明

| 远端 Release 状态 | 默认行为 | 说明 |
|------------------|---------|------|
| 不存在 | `gh release create` | 用聚合后的 changelog 作 body |
| 已存在 | `gh release edit` | **仅更新 title / body**，保留所有 assets |
| 已存在 + `--force-recreate` | `delete` 然后 `create` | 会丢失现有 assets，仅在确实需要重建时使用 |

##### Body 聚合策略

发版到 GitHub 上的 Release 不一定是连续的——可能 v3.4.2、v3.4.3 都打了 tag 但只有 v3.4.4 才决定建 Release。这时如果只把 v3.4.4 的 changelog 当 body，用户就看不到中间两个版本的变更。

所以 `release-github.sh` 默认会做**区间聚合**：

1. 通过 `gh release list` 拉取所有已存在的 Release，找出**语义版本严格小于 `<tag>`** 的最近一个，记为 `START_TAG`（也就是"上一个已发布到 GitHub Releases 的 tag"）。如果一个都没有，`START_TAG` 为空。
2. 在 `docs/changelog/v*.md` 里挑出所有满足 `START_TAG < t <= <tag>` 的文件，按版本号**倒序**（新→旧）。
3. 用 `<tag>` 自己的文件作主体，剩下的旧 tag 内容塞到 `## 📚 Included previous changes` 段，每个用 `<details>` 折叠包裹（避免页面太长）。

**这样无论你跳几个版本才建 Release，body 里都能看到完整的变更历史。**

跳过聚合：

- `--single`：明确说"我只要这一个 tag 的 changelog"，跳过所有聚合逻辑
- `--since=vA.B.C`：手动指定起点（替换自动从 GitHub Release 推断的逻辑）

##### 前置条件

- 远端 origin 存在 tag `<tag>`（脚本会校验）
- `docs/changelog/<tag>.md` 已存在（不存在时报错并提示先跑 `release.sh`）
- 本地装了 `gh` 且已 `gh auth login`，或 `.release` 配置了 `RELEASE_GH_TOKEN`

##### 与 `release.sh` 的协作

```
release.sh vX.Y.Z              # 生成 changelog / 打 tag / push (默认不触发 CI)
        │
        ├── 需要构建产物时: release.sh vX.Y.Z --build
        │       └── CI 跑完: build-package.yml 自动创建 Release + 上传 assets
        │
        └── 想美化 body / 想聚合中间漏发的 tag 时:
            release-github.sh vX.Y.Z   # body 用 docs/changelog/vX.Y.Z.md (+ 中间漏发的旧 tag)
```

如果 CI 还没跑完就先想建 Release（例如只做 source release），直接 `release-github.sh vX.Y.Z` 也可以——它会以 `create` 模式跑，等 CI 跑到上传 asset 那一步就会把附件加到这个已存在的 Release 上。

### 4.3 详细步骤（手动备选流程）

#### Step 1 - 代码冻结

```bash
git checkout master
git pull --ff-only
git checkout -b release/v3.4.2
```

#### Step 2 - 更新版本号与 CHANGELOG

修改 `version.py`：

```python
APP_VERSION = 'v3.4.2'
```

在 `docs/changelog/<tag>.md` 中新建本次变更（推荐直接使用 `scripts/release.sh` 自动生成；手动撰写时格式参考已有版本文件）。

提交：

```bash
git add version.py docs/changelog/v3.4.2.md
git commit -m "release: bump version to v3.4.2"
```

#### Step 3 - 打 Tag 并合并

```bash
# 合并回 master
git checkout master
git merge --no-ff release/v3.4.2
git push origin master

# 打 Tag
git tag -a v3.4.2 -m "Release v3.4.2"
git push origin v3.4.2
```

#### Step 4 - 构建产物

##### 4.1 Docker 镜像（自动）

GitHub Actions 监听 Tag 推送后会执行 `docker/Dockerfile` 与 `docker/debian.Dockerfile`，构建 amd64 / arm64 双架构镜像并推送到 Docker Hub。

如需手动构建：

```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t joneezhu/NasTools:v3.4.2 \
  -t joneezhu/NasTools:latest \
  -f docker/Dockerfile \
  --push .
```

##### 4.2 PyInstaller 可执行文件

进入 `package/`，依次在 macOS / Windows / Linux 三平台执行：

```bash
# 安装 PyInstaller
pip install pyinstaller==5.13.0

# 构建（具体 spec 文件见 package/）
pyinstaller package/nastool.spec

# 产物在 dist/ 下，按平台命名：
mv dist/nastool dist/nastool_linux_v3.4.2
```

> 三平台构建建议使用 GitHub Actions Matrix Job 自动化，避免手动差异。

#### Step 5 - 冒烟测试

| 项 | 操作 | 期望 |
|----|------|------|
| 镜像启动 | `docker run -d -p 3000:3000 joneezhu/NasTools:v3.4.2` | 容器健康，端口可访问 |
| 登录 | 浏览器访问 `http://localhost:3000`，`admin/password` | 能进入主页 |
| 数据库迁移 | 用旧版本 `user.db` 启动新版本 | Alembic 自动升级，无报错 |
| TMDB 识别 | 配置 Key 后搜索一部电影 | 能拉到元数据 |
| 下载器对接 | 配置 qb / tr 并测试连通 | 显示「连接成功」 |
| 通知 | 微信 / TG 测试通知 | 能收到测试消息 |
| 配置热更 | 修改 `config.yaml` | 日志显示热加载成功 |

#### Step 6 - 发布 GitHub Releases

在 GitHub Releases 页面：

- **Tag**：`v3.4.2`
- **Title**：`v3.4.2 - <一句话标题>`
- **Body**：粘贴 `docs/changelog/<tag>.md` 内容（或直接用 `scripts/release-github.sh` 自动同步）
- **Attachments**：上传 PyInstaller 三平台二进制
- 勾选「Set as the latest release」（正式版），或「Set as a pre-release」（rc / beta）

#### Step 7 - 公告与通知

- 在仓库 Discussions 发布版本说明
- 在 README 顶部更新版本徽章
- 通过 Telegram / 微信群（如有）公告关键变更
- 关闭对应里程碑的 Issue / PR

---

## 五、回滚方案

### 5.1 Docker 用户

```bash
# 回滚到上一个稳定版本
docker pull joneezhu/NasTools:v3.4.1
docker stop nas-tools && docker rm nas-tools
# 重新 docker run（使用 v3.4.1 tag）
```

> 注意：若新版本执行了 Alembic 数据库升级，回滚旧版本前必须**先恢复 `user.db` 备份**，否则可能因 schema 不一致启动失败。

### 5.2 源码用户

```bash
git fetch --tags
git checkout v3.4.1
python3 -m pip install --force-reinstall -r requirements.txt
# 恢复 user.db / config.yaml 备份
```

### 5.3 紧急下线

如发现严重问题需要紧急撤回：

1. 在 Docker Hub 将 `latest` 重新指向上一稳定版本
2. 在 GitHub Releases 将问题版本标记为「pre-release」
3. 发布 Hotfix `vX.Y.Z+1`，按正常流程走完发布闭环

---

## 六、产物校验

### 6.1 SHA256 校验

PyInstaller 产物建议附带 `SHA256SUMS.txt`：

```bash
shasum -a 256 nastool_linux_v3.4.2 nastool_macos_v3.4.2 nastool_windows_v3.4.2.exe \
  > SHA256SUMS.txt
```

### 6.2 Docker 镜像签名（可选）

启用 Docker Content Trust：

```bash
export DOCKER_CONTENT_TRUST=1
docker push joneezhu/NasTools:v3.4.2
```

---

## 七、发布频率

- **PATCH（v3.4.x）**：按需发布，遇到关键 Bug 即可
- **MINOR（v3.x.0）**：约 1~3 个月一次，伴随功能合并
- **MAJOR（vX.0.0）**：架构变更时，**必须在 CHANGELOG 中详细说明迁移路径**

---

## 八、检查清单（Release Checklist）

```
□ version.py 版本号已更新
□ docs/changelog/<tag>.md 已生成（release.sh 自动）
□ 所有 P0/P1 Bug 已闭环
□ requirements.txt 已锁定 + Pip Audit
□ package_list*.txt 已同步
□ Alembic 迁移脚本已新增并自测
□ tests/ 全部通过
□ Docker amd64 / arm64 镜像构建成功
□ PyInstaller 三平台二进制构建成功
□ 冒烟测试 7 项全部通过
□ 旧 DB 兼容性验证通过
□ GitHub Releases 已发布并附产物
□ SHA256SUMS.txt 已附上
□ README 版本徽章已更新
□ 公告已发出
```

---

> 发布流程的稳定性 > 发布频率。每一次发布都应可追溯、可回滚、可验证。
