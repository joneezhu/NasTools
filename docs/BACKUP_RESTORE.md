# NasTools 备份与恢复指引

> 适用版本：v3.4.2 及之后；本文档同时覆盖 **本机迁移** 与 **跨分支导入**（从其他人/其他 fork 的 NasTools 导入数据）两种场景。

---

## 1. 你应该先了解的几件事

### 1.1 备份内容

每个备份 zip 包含以下文件（位于 `<config>/` 目录下，容器中通常是 `/config`）：

| 文件 | 作用 | 是否必需 |
|---|---|---|
| `user.db` | 主数据库（站点、订阅、刷流任务、过滤规则、用户、洗版、自定义识别词等） | ✅ 必需 |
| `config.yaml` | 全局配置（端口、API key、消息通知、媒体服务器等） | 推荐 |
| `default-category.yaml` | 二级分类策略 | 推荐 |
| `backup_meta.json` | **元数据**（来源版本、alembic_version、创建时间），由 v3.4.2+ 自动生成 | 自动 |

### 1.2 不会被备份的内容

- **媒体文件本身**（视频、字幕、海报）—— 这些不属于 NasTools 配置范畴
- **下载器（qBittorrent / Transmission）的 .torrent 与做种状态** —— 由下载器自身管理
- **日志文件**（`logs/`）
- **插件运行时数据**（部分插件会写入 `user.db`，会被备份；但插件自带的本地缓存目录不会）

### 1.3 默认裁剪表（非完整备份）

为减小备份体积，UI 默认会从 `user.db` 中**删除**以下高频写入但可重建的表：

```
SEARCH_RESULT_INFO  RSS_TORRENTS         DOUBAN_MEDIAS
TRANSFER_HISTORY    TRANSFER_UNKNOWN     TRANSFER_BLACKLIST
SYNC_HISTORY        DOWNLOAD_HISTORY     alembic_version
```

如需保留这些表，使用 CLI `--full`（参见第 4 节）。

---

## 2. 两种恢复模式（重点）

| 模式 | 整库覆盖（replace） | 智能合并（merge） |
|---|---|---|
| 操作 | 用备份的 `user.db` 直接覆盖本机 | 仅把业务数据按表 INSERT 进本机 db，**保留本机 schema + alembic_version** |
| 适合场景 | **同一分支同一版本**之间迁移 / 还原 | **跨分支 / 跨版本** 导入（包括从他人 fork 导入） |
| schema 风险 | 如果备份与本机版本不同，可能字段不匹配 | 自动取列交集，本机额外的列保持默认值 |
| alembic | 备份的 alembic_version 会写入 | **保留本机** alembic_version，启动时自动迁移到 head |
| config.yaml | 默认连同恢复（可关） | 默认**不**恢复（避免覆盖本机端口/路径） |

> **建议**：从其他人 NasTools fork 导入数据，**始终选择「智能合并」**。

---

## 3. 通过 Web UI 备份与恢复

### 3.1 打开入口

服务管理 → 找到 **「备份与恢复」** 卡片 → 点击右上角播放按钮 → 弹出「备份&恢复」对话框。

### 3.2 备份当前配置

1. 点击底部 **「备份当前配置」**
2. 浏览器会**自动下载**一个 `bk_YYYYMMDDHHMMSS.zip`
3. 妥善保存（建议放到 NAS 共享盘 / 云盘）

> 同一份备份会同时落地到 `<config>/backup_file/` 目录，便于在容器里直接归档。

### 3.3 恢复备份（含跨分支导入）

1. 把 zip 文件**拖到上传区**（或点击选择）
2. 上传成功后，下方会自动展示**备份信息**：
   - 来源版本（`app_version`）
   - 来源 alembic vs 本机 alembic（**不一致会高亮提醒**并自动切到「智能合并」）
   - 包含的文件（config.yaml / default-category.yaml / user.db）
   - 数据表清单与每张表的行数（前 8 张）
3. 选择 **恢复模式**：
   - **整库覆盖（replace）**：本机迁移、回滚、同版本场景
   - **智能合并（merge）**（蓝色徽章）：跨分支/跨版本，**导入他人备份首选**
4. 是否勾选 **「同时覆盖 config.yaml / default-category.yaml」**：
   - replace 模式默认 ✅（除非你想保留本机配置）
   - merge 模式默认 ❌（避免覆盖本机端口、API、消息通道等）
5. 点击 **「恢复配置」** → 二次确认 → 等待结果
6. 提示成功后，**重启 NasTools**（容器：`docker restart nas-tools`；面板：设置 → 重启）

### 3.4 出问题怎么办？

恢复操作会自动把覆盖前的文件备份到：

```
<config>/backup_file/rollback_YYYYMMDDHHMMSS/
├─ config.yaml
├─ default-category.yaml
└─ user.db
```

异常时，把这三个文件复制回 `<config>/` 即可回到恢复前状态。

---

## 4. 通过 CLI 脚本（脚本/计划任务/迁移）

脚本位置：`scripts/nt-backup.sh`

### 4.1 在容器中调用

Docker 镜像已经包含 Python 3，进入容器：

```bash
docker exec -it nas-tools bash
cd /nas-tools          # 镜像内仓库根目录
./scripts/nt-backup.sh backup --config /config --full
# 输出：/config/backup_file/bk_20260524032227.zip
```

容器外触发：

```bash
docker exec nas-tools bash -lc \
  '/nas-tools/scripts/nt-backup.sh backup --config /config'
```

### 4.2 命令速查

```bash
# 1) 备份（默认裁剪非业务表，--full 全量）
nt-backup.sh backup --config /config [--out <dir>] [--full]

# 2) 查看 zip 内容（看来源版本、表行数）
nt-backup.sh inspect --file bk_20260524.zip --config /config

# 3) 整库覆盖恢复
nt-backup.sh restore --file bk_20260524.zip --config /config --mode replace
# 想保留本机 config.yaml 不被覆盖：加 --keep-config-yaml

# 4) 跨分支/跨版本智能合并恢复（推荐用于他人备份）
nt-backup.sh restore --file 朋友的_bk.zip --config /config --mode merge
```

### 4.3 计划任务示例（每天 04:30 自动备份并轮转 7 天）

宿主机 cron（容器名 `nas-tools`）：

```cron
30 4 * * * docker exec nas-tools bash -lc '/nas-tools/scripts/nt-backup.sh backup --config /config' \
  && find /path/to/backup_dir -name 'bk_*.zip' -mtime +7 -delete
```

容器内 cron 同理（用 supervisord 起一个 cron 服务），不展开。

---

## 5. 跨分支导入完整流程（从他人 fork 取备份）

> 场景：朋友用 [hsuyelin/nas-tools](https://github.com/hsuyelin/nas-tools)，你用本仓库（joneezhu/NasTools），想把朋友的站点/订阅/刷流任务搬过来。

### Step 1 — 朋友导出

让朋友在他的 NasTools 上：服务管理 → 备份恢复 → **「备份当前配置」** → 把下载到的 `bk_xxx.zip` 发给你。

### Step 2 — 你导入

打开你的 NasTools UI → 服务管理 → 备份恢复：

1. 拖入朋友的 zip
2. **检查信息卡片**：
   - 来源版本 vs 本机版本（`v3.x.x` 与 `v3.x.x` 的差异）
   - 来源 alembic vs 本机 alembic（**不一致 = 必须用智能合并**，UI 会自动切换并高亮）
3. 模式选择 **「智能合并」**
4. **不要**勾选「同时覆盖 config.yaml」 —— 你的端口/通知/路径配置不该被替换
5. 点击 **「恢复配置」** → 等待 → 重启服务

### Step 3 — 重启后核对

- 站点列表是否完整（设定 → 站点管理）
- 订阅是否搬过来了（订阅管理 → 电影/电视剧）
- 刷流任务、自定义识别词、过滤规则是否都在
- 检查 `logs/nas-tools.log` 是否有 `alembic upgrade` 成功的记录

### 已知差异表（合并时本机若没有该表会被跳过）

不同分支可能存在的额外表（比如某些 fork 加的 PT_DOMAIN_MAP、CUSTOM_PARSER 等），合并模式会**自动跳过本机没有的表**，不会报错也不会破坏本机 schema。如果你需要的字段刚好在跳过的表里，参考第 6 节手工合并。

---

## 6. 极端场景：手工合并某张表

如果 `inspect` 看到来源 zip 里有本机没有的表（例如朋友的 `MY_CUSTOM_RULES`），又想要那张表的数据：

```bash
# 1) 解压备份
unzip bk_xxx.zip -d /tmp/peer
# 2) 查看建表 SQL
sqlite3 /tmp/peer/user.db ".schema MY_CUSTOM_RULES"
# 3) 在本机 db 里建同名表（结构必须能被你的代码识别才有意义）
sqlite3 /config/user.db < table.sql
# 4) 用 .dump 倒数据
sqlite3 /tmp/peer/user.db ".dump MY_CUSTOM_RULES" \
  | grep -v "^CREATE" | sqlite3 /config/user.db
```

> ⚠️ 仅当本机代码能识别这张表时才有意义。否则只是数据库里多一张孤立的表。

---

## 7. 安全清单

- [x] 恢复前**停止定时任务**（避免恢复进行中触发刷流/转移）
- [x] 容器场景：恢复前 `docker stop nas-tools`，恢复后 `docker start`（或在 UI 重启）
- [x] 来源不明的 zip 先用 `inspect` 看清楚再恢复
- [x] 跨分支首选 **smart merge**，不要轻易整库覆盖
- [x] 重要环境定期跑一次 `nt-backup.sh backup` 自动归档

---

## 8. 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 恢复后启动失败，日志报 `no such column` | 整库覆盖了一个旧版本 db，本机代码访问了新字段 | 把 `<config>/backup_file/rollback_*/user.db` 复制回去，改用智能合并模式重做 |
| 恢复后某些站点信息丢失 | 备份是「非完整模式」，部分历史表已裁剪 | 这是预期行为；只丢历史明细，配置类数据不会丢 |
| 智能合并提示 `0 张表` | 备份 schema 与本机完全不兼容 / 上传的不是 NasTools 备份 | 用 `inspect` 检查是不是合法 zip + 是否包含 user.db |
| 浏览器下载备份失败 | 反代超时（zip 较大） | 用 CLI `nt-backup.sh backup` 在容器内生成，再拷出去 |
| 恢复完整后 alembic 状态混乱 | 整库覆盖时引入了陈旧的 alembic_version | 进容器删除该表：`sqlite3 /config/user.db "DROP TABLE alembic_version"`，重启即可重新 upgrade |

---

## 9. 文件 / API 索引

| 内容 | 位置 |
|---|---|
| CLI 脚本 | `scripts/nt-backup.sh` |
| Web UI | `web/templates/service.html` 的「备份&恢复」模态框 |
| 后端备份逻辑 | `web/action.py` `WebAction.backup()` |
| 后端恢复逻辑 | `web/action.py` `__restory_backup` / `__inspect_backup` / `__merge_user_db` |
| HTTP 路由 | `POST /backup` 下载 / `POST /upload` 上传 zip / `POST /do` action=`restory_backup`、`inspect_backup` |

---

_最后更新：2026-05-24_
