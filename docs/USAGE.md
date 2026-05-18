# NAStool 使用文档（USAGE）

> 适用版本：v3.4.1
> 文档编写：2026-05-18
> 项目路径：`nas-tools`

本文档面向 **首次部署 / 日常使用** 的用户，介绍如何安装、配置、运行 NAStool，并梳理核心功能模块的常用操作。如需了解项目内部结构，请阅读 `PROJECT_REPORT.md`；如需发布 / 升级，请阅读 `RELEASE.md` 与 `CHANGELOG.md`。

---

## 一、概览

**NAStool** 是一款面向 NAS / PT 用户的一站式媒体自动化平台，核心能力：

- **资源订阅与下载**：RSS 订阅、关键词搜索、PT 站点抓取
- **媒体识别与刮削**：基于 TMDB / 豆瓣，自动重命名、分类、刮削
- **下载器集成**：qBittorrent / Transmission / Aria2 / 115 / PikPak
- **媒体服务器联动**：Emby / Jellyfin / Plex 自动入库与刷新
- **PT 全生命周期**：签到、刷流（Brush）、辅种（IYUU）、做种维护
- **多渠道消息通知**：微信 / Telegram / Slack / Bark / PushDeer / Gotify
- **插件化扩展**：30+ 内置插件，可在 WebUI 中一键启用

支持的运行形态：

| 形态 | 适用人群 | 推荐度 |
|------|---------|--------|
| Docker（官方推荐） | 大多数 NAS / Linux 用户 | ★★★★★ |
| 源码运行 | 开发者 / 调试 / 二次开发 | ★★★★ |
| PyInstaller 可执行文件 | Windows / macOS 桌面用户 | ★★★ |

---

## 二、环境要求

### 2.1 公共要求

- **Python**：仅支持 **3.10**（Docker 镜像内置 `python:3.10.11-alpine`）
- **架构**：amd64 / arm64
- **网络**：能访问 `api.themoviedb.org`（或 `api.tmdb.org`）、`webservice.fanart.tv`，以及目标 PT 站
- **TMDB API KEY**：必须申请，前往 <https://www.themoviedb.org/settings/api>

### 2.2 系统级配置（仅 Linux 宿主机需要）

为支持目录同步（inotify），在宿主机执行：

```bash
echo fs.inotify.max_user_watches=524288   | sudo tee -a /etc/sysctl.conf
echo fs.inotify.max_user_instances=524288 | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

---

## 三、安装与启动

### 3.1 Docker 方式（推荐）

#### 3.1.1 docker run

```bash
docker pull joneezhu/NasTools:latest

docker run -d \
  --name nas-tools \
  --hostname nas-tools \
  -p 3000:3000 \
  -v /your/path/config:/config \
  -v /your/media:/media \
  -e PUID=0 \
  -e PGID=0 \
  -e UMASK=022 \
  -e NASTOOL_AUTO_UPDATE=false \
  -e NASTOOL_CN_UPDATE=false \
  --restart=always \
  joneezhu/NasTools:latest
```

#### 3.1.2 docker-compose

新建 `docker-compose.yml`：

```yaml
version: "3"
services:
  nas-tools:
    image: joneezhu/NasTools:latest
    container_name: nas-tools
    hostname: nas-tools
    ports:
      - "3000:3000"
    volumes:
      - ./config:/config
      - /your/media:/media
    environment:
      - PUID=0
      - PGID=0
      - UMASK=022
      - NASTOOL_AUTO_UPDATE=false
      - NASTOOL_CN_UPDATE=false
      # - REPO_URL=https://ghproxy.com/https://github.com/joneezhu/NasTools.git
    restart: always
    network_mode: bridge
```

启动：

```bash
docker-compose up -d
```

#### 3.1.3 关键环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `PUID` / `PGID` | 容器运行用户 UID / GID，**必须与媒体文件 owner 一致**，否则硬链接会失败 | `0` |
| `UMASK` | 文件掩码，建议 `022` | `000` |
| `NASTOOL_AUTO_UPDATE` | 启动时自动 `git pull` 更新代码 | `false` |
| `NASTOOL_CN_UPDATE` | 自动更新时是否使用国内源（清华 PyPI） | `true` |
| `NASTOOL_VERSION` | 切换分支，`master` / `dev` | `master` |
| `REPO_URL` | 自定义仓库地址，可换 ghproxy 镜像 | 官方仓库 |

> 关于硬链接的目录映射：必须将媒体源目录与媒体库目录的 **共同上级目录** 映射到容器内，且双侧路径一致，否则 Docker 会判定跨盘失败。

### 3.2 源码运行

```bash
# 1. 克隆仓库（含子模块）
git clone -b master https://github.com/joneezhu/NasTools --recurse-submodules
cd nas-tools

# 2. 安装 Python 3.10 与 Cython
python3 -m pip install Cython

# 3. 安装依赖
python3 -m pip install --force-reinstall -r requirements.txt

# 4. 设置配置路径
export NASTOOL_CONFIG="$(pwd)/config/config.yaml"
export NASTOOL_LOG="$(pwd)/config/logs"   # 可选

# 5. 启动
nohup python3 run.py &
```

启动后访问：<http://localhost:3000>，默认账号 `admin / password`。

### 3.3 可执行文件运行

从 GitHub Releases 下载对应平台的二进制（macos / windows / linux），解压后：

```bash
chmod +x nastool        # *nix
./nastool               # 启动
```

> macOS 12+ 需在「设置 → 隐私与安全性」中允许任意开发者运行。

---

## 四、首次配置

### 4.1 登录 WebUI

- 地址：`http://<你的IP>:3000`
- 默认账号：`admin`
- 默认密码：`password`

**首次登录后请立即修改密码（设定 → 用户管理）。**

### 4.2 必填项清单

| 模块 | 配置项 | 说明 |
|------|--------|------|
| 设定 → 基础设置 | TMDB API KEY | 元数据识别核心 |
| 设定 → 基础设置 | 代理（可选） | 如需访问 TMDB / Telegram |
| 设定 → 媒体库 | 电影 / 电视剧 / 动漫路径 | 媒体最终存放目录 |
| 设定 → 媒体库 | 媒体服务器 | Emby / Jellyfin / Plex 三选一 |
| 设定 → 下载器 | 下载器设置 | qb / tr / aria2 等 |
| 设定 → 站点 | PT 站点 Cookie | 用于签到、订阅、刷流 |
| 设定 → 消息通知 | 通知渠道 | 微信 / TG / Bark 等 |

### 4.3 配置文件直接编辑

如需在 WebUI 之外编辑：

- 路径：`<config_dir>/config.yaml`
- 格式：YAML（**冒号后必须有空格，不能用全角标点**）
- 修改后会被 `watchdog` **热加载**，无需重启容器

主要节点：

```yaml
app:        # 全局应用（端口、日志、TMDB Key、代理、登录账号）
media:      # 媒体库路径与服务器
emby/jellyfin/plex:   # 三选一详情
downloaddir:          # 下载目录列表
qbittorrent/transmission/aria2/pikpak/...:  # 下载器
sync:       # 目录同步
pt:         # PT 站点签到 / RSS / 刷流
message:    # 消息通知
indexer:    # 索引器
laboratory: # 实验性功能
```

---

## 五、核心功能使用指引

### 5.1 媒体识别与重命名

1. **设定 → 媒体库**：填写电影 / 电视剧 / 动漫目录
2. **设定 → 基础设置**：TMDB Key、匹配模式（`normal` / `strict`）
3. **媒体整理 → 手动识别**：处理识别失败的资源
4. **媒体整理 → 历史记录**：查看历史转移记录，可重新识别 / 删除

文件转移方式（在下载目录配置中选择）：

| 方式 | 含义 | 注意 |
|------|------|------|
| `link` | 硬链接（推荐） | 源 / 目的目录必须同一文件系统 |
| `softlink` | 软链接 | 容器内外路径需一致 |
| `copy` | 复制 | 占用双倍空间 |
| `move` | 移动 | 影响做种，慎用 |
| `rclone` / `rclonecopy` | 通过 rclone 操作网盘挂载 | 需先配置 rclone |

### 5.2 RSS 订阅

- **订阅 → 电影 / 电视剧**：手动添加，支持 TMDB ID / 关键词 / 豆瓣榜单
- **订阅 → 自动添加**：从豆瓣想看 / 收藏夹自动同步
- **订阅日历**：查看订阅项的播出排期

订阅刷新间隔：`config.yaml → pt.rss_interval`，默认 5 分钟。

### 5.3 搜索与下载

- **搜索资源**：站点内搜索（需配置索引器）
- **手动下载**：从搜索结果直接推送到下载器
- **下载管理**：实时查看 qb/tr/aria2 任务状态

### 5.4 站点签到与刷流

- **设定 → 站点**：批量管理 PT 站点 Cookie
- **服务**：内置 PT 签到、统计、辅种（IYUU）任务
- **刷流（Brush）**：插件「Brush Task」中配置规则（最低做种、保种空间、删除条件等）

### 5.5 媒体服务器联动

- **Emby / Jellyfin / Plex Webhook**：在媒体服务器中配置 Webhook 指向 NAStool 的回调地址，实现观看记录同步
- **媒体库刷新**：转移完成后自动调用媒体服务器 API 刷新

### 5.6 消息通知

进入 **设定 → 消息通知**，可单独开启每种通知类型（搜索 / 下载 / 入库 / 站点签到 / 系统消息），并对应到不同渠道：

- WeChat（企业微信 / Server 酱）
- Telegram Bot
- Slack
- Bark / PushDeer / IYUU / Gotify / Synology Chat / 飞书 / Pushplus / 钉钉 / Webhook

### 5.7 插件中心

进入 **插件**，可启用：自动签到、字幕下载、自定义脚本、容器管理、Cookie 同步、自动备份、TMDB 番剧补全、磁盘空间监控等 31 个内置插件。每个插件可独立配置定时调度、参数和通知。

---

## 六、常见问题速查

| 现象 | 处理 |
|------|------|
| 启动报错 `inotify instance limit reached` | 在宿主机执行第二节中的 `sysctl` 命令 |
| 启动报错 `no such column` | 数据库 schema 不一致，用 SQLite 浏览器打开 `config/user.db`，删除 `alembic_version` 表后重启 |
| 网络无法访问 TMDB | 设定 → 基础设置 → 代理；或将 `tmdb_domain` 改为 `api.tmdb.org` |
| 微信 / TG 消息无法跳转 | 在 `config.yaml → app.domain` 填写外网 URL（含端口） |
| 容器更新失败 | 设置 `NASTOOL_CN_UPDATE=true` 使用国内源；或重新 `docker pull` 镜像 |
| 硬链接失败 | 确保源 / 目的同分区，且 Docker 上挂的是共同上级目录 |

更多 FAQ 详见 `README.md`。

---

## 七、目录与文件位置速查

| 路径 | 说明 |
|------|------|
| `/config/config.yaml` | 主配置文件 |
| `/config/user.db` | 用户数据 / 历史记录 / 订阅 SQLite |
| `/config/logs/` | 日志目录（`logtype=file` 时） |
| `/config/category/` | 自定义分类策略 yaml |
| `/nas-tools/`（容器内） | 程序代码目录 |

---

## 八、安全与运维建议

1. **修改默认账号密码**，禁用默认 `admin/password`
2. **不要将 3000 端口直接暴露公网**，建议搭配反向代理 + HTTPS
3. **定期备份** `config/` 目录（特别是 `config.yaml` 与 `user.db`）
4. **关闭 Debug 模式**：`config.yaml → app.debug: false`
5. **谨慎开启自动更新**：生产环境建议 `NASTOOL_AUTO_UPDATE=false`，更新前先备份
6. **PT Cookie 安全**：尽量使用站点专用账号，避免与个人主账号绑定

---

> 如有任何问题或建议，请提交 Issue 或参考 `README.md` 中的开发路线讨论链接。
