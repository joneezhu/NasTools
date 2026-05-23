# NAStool 发布文档（RELEASE）

> 适用版本：v3.4.1
> 文档编写：2026-05-18
> 适用范围：维护者 / 发布工程师 / 自建分发渠道用户

本文档定义了 NAStool 项目的 **版本号规范、发布流程、构建产物、回滚方案** 与 **后续发布检查清单**。日常使用请参考 `USAGE.md`，版本变更明细请参考 `CHANGELOG.md`。

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
- [ ] `version.py` 的 `APP_VERSION` 已更新
- [ ] `CHANGELOG.md` 已补充本次变更条目
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

1. 触发 `build.yml` / `build-beta.yml` / `build-package.yml` 三条 GitHub Actions 流水线
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
gh workflow list -R joneechua/NasTools
# 应能看到 build.yml / build-beta.yml / build-package.yml
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

# 正式发布（自动加载 .release, push + 触发流水线）
scripts/release.sh v3.4.2

# 仅本地操作（不 push、不触发 CI，调试用）
scripts/release.sh v3.4.2 --no-push

# 只想打 tag 不触发 CI（无需 .release）
scripts/release.sh v3.4.2 --no-build

# Tag message 不使用 emoji（兼容老旧 git 客户端）
scripts/release.sh v3.4.2 --no-emoji

# 调整 tag message 中变更条目上限（默认 12）
scripts/release.sh v3.4.2 --tag-limit=20
```

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
3. 在 `docs/CHANGELOG.md` 的 `[Unreleased]` 之后插入新版本节，并把 `[Unreleased]` 重置为模板
4. 修改 `version.py` 中的 `APP_VERSION`
5. 创建 `release: bump version to vX.Y.Z` commit，附带 5 条核心修改点
6. 打 annotated tag，tag message 内嵌结构化变更摘要（标题区 + 类目分组 + emoji 图标，默认上限 12 条，可用 `--tag-limit=N` 调整）
7. push master + tag 到远端
8. 通过 `gh workflow run` 触发 `build.yml`（Docker Hub）与 `build-package.yml`（二进制 + Release）

#### 幂等行为（可重入）

脚本会先检查目标版本号在远端的状态，避免重复发布或漏发安装包：

| 场景 | tag 是否存在 | GitHub Release 安装包 | 行为 |
|------|------------|----------------------|------|
| A | ❌ 不存在 | — | 走完整流程（生成 changelog → 改 version → commit → tag → push → 触发三条流水线） |
| B | ✅ 存在 | ✅ 至少 1 个 asset | 直接退出，提示 Release 链接（无事可做） |
| C | ✅ 存在 | ❌ 缺失 | 跳过 commit/tag/push，**仅基于已有 tag 重跑 `build-package.yml`** 出包 |

> 场景 C 的典型用例：tag 已打但打包流水线失败/被取消，重跑 `scripts/release.sh vX.Y.Z` 即可补出安装包，不会再生成新的 commit 或 tag。
>
> 场景 B/C 都需要本地 **gh CLI 已登录**（脚本会用 `gh release view` 判定 assets 数）。未登录时脚本会拒绝执行，避免误把"无权限"判定成"无安装包"导致重复发版。

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

在 `CHANGELOG.md` 顶部新增本次条目（具体格式见 `CHANGELOG.md`）。

提交：

```bash
git add version.py CHANGELOG.md
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
- **Body**：粘贴 `CHANGELOG.md` 中本版本对应章节
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
□ CHANGELOG.md 顶部已新增条目
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
