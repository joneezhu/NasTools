# setuptools 版本问题排查与修复

## TL;DR

**症状**: 群晖套件中心升级或容器重启后，NasTools 起不来，日志里出现：

```
ModuleNotFoundError: No module named 'pkg_resources'
File ".../supervisor/options.py", line 13
```

**根因**: setuptools 升级到 81+，PyPA 在该版本彻底移除 `pkg_resources` 子模块，supervisor 仍在 import，于是套件 ImportError 起不来。

**一键修复**（SSH root 进入群晖或容器执行）：

```bash
# 群晖套件
cd /var/packages/NASTool/target
./bin/python3 -m pip install --upgrade --force-reinstall \
  'pip<25' 'setuptools<70' wheel
synopkg restart NASTool

# Docker 容器
docker exec -it nas-tools sh
pip install --upgrade --force-reinstall 'pip<25' 'setuptools<70' wheel
exit
docker restart nas-tools
```

---

## 完整背景

NasTools 项目对 setuptools 有严格的版本上限要求：**`setuptools<70`**。

### 为什么是 `<70`

两个上游依赖联手卡死了上限：

| 包 | 限制 | 原因 |
|---|---|---|
| `fast-bencode==1.1.3` | `setuptools<70` | 上古 sdist，无 wheel；setup.py 调用 `distutils.parse_command_line`，setuptools 70 删除该 API，安装即报 `TypeError: argument of type 'NoneType' is not iterable` |
| `supervisor 4.x` | `setuptools<81` | supervisor 仍 `import pkg_resources`；setuptools 81 移除该模块，supervisor 启动即 ImportError |
| 打包脚本（PyInstaller） | `setuptools<70` | 依赖 setuptools 自带 `_vendor/pyparsing/diagram/`，setuptools 69 移除该目录 |

**取交集 → `setuptools<70` 是唯一安全区间**。

### 项目内的多重防线（v3.4.x 起）

我们在所有可能动 setuptools 的地方都钉了上限：

1. **`requirements.txt` 顶部**：`pip<25` + `setuptools<70`，pip resolver 装包时强制锁定
2. **`docker/Dockerfile` / `docker/debian.Dockerfile`**：`pip install --upgrade 'pip<25' 'setuptools<70'`
3. **`docker/rootfs/etc/s6-overlay/.../init-010-update/run`**：容器启动 hook 同样钉死
4. **`package/builder/Dockerfile` 与 `.github/workflows/build-package.yml`**：CI 打包路径钉死
5. **`app/helper/setuptools_guard.py` + `run.py`**：应用层启动自检，环境失态时打印告警 + 设置 `NT_SETUPTOOLS_DEGRADED` 环境变量

但是——

### 我们控制不了的部分

**群晖 NasTool 套件包的 install.sh / 升级钩子**不在 git 仓库里，是套件作者打 spk 时打包的。该脚本里有类似 `pip install --upgrade setuptools` 的命令**没有钉版本上限**，导致：

- 套件中心版本号变更 → 重跑 install.sh → setuptools 被拉到最新 → 套件锁死
- 这种情况只能 SSH 手动修复，应用层无法预防

---

## 修复操作详解

### 群晖 NasTool 套件

```bash
# 1. SSH 登录群晖, 切换到 root
sudo -i

# 2. 进入套件目录
cd /var/packages/NASTool/target

# 3. 确认现状 (可选, 用于诊断)
ls lib/python3.10/site-packages/ | grep -iE "setuptools|pkg_res"
# 期望看到 setuptools-X.Y.Z.dist-info, X<70

# 4. 强制重装 (必须用套件自带 python, 不是系统 python)
./bin/python3 -m pip install --upgrade --force-reinstall \
  'pip<25' 'setuptools<70' wheel

# 5. 验证
./bin/python3 -c "import pkg_resources; print('pkg_resources OK:', pkg_resources.__file__)"
./bin/python3 -c "from supervisor import options; print('supervisor OK')"

# 6. 重启套件
synopkg restart NASTool
synopkg status NASTool

# 7. 进程检查
ps -ef | grep -E "supervisor|nas-tools" | grep -v grep
```

### Docker 容器

```bash
# 1. 进入容器
docker exec -it nas-tools sh   # alpine
# 或
docker exec -it nas-tools bash # debian

# 2. 强制重装
pip install --upgrade --force-reinstall 'pip<25' 'setuptools<70' wheel

# 3. 验证
python3 -c "import pkg_resources; print('OK')"

# 4. 退出并重启容器
exit
docker restart nas-tools
```

### 网络抽风时改用国内镜像

```bash
./bin/python3 -m pip install --upgrade --force-reinstall \
  'pip<25' 'setuptools<70' wheel \
  -i https://mirrors.aliyun.com/pypi/simple/
```

### PEP 668 拦截时

某些较新的 Python 发行版会以 "externally-managed-environment" 拒绝 pip install。加 `--break-system-packages`：

```bash
./bin/python3 -m pip install --upgrade --force-reinstall \
  'pip<25' 'setuptools<70' wheel \
  --break-system-packages
```

套件 venv 不归系统包管理器管，加这个开关无副作用。

---

## 兜底方案

如果上面修复不动，按代价从低到高：

1. **套件中心 → NASTool → 操作 → 修复**（保留配置）
2. **卸载重装套件**（配置目录 `/var/packages/NASTool/etc/` 默认保留，但务必先备份 `config/config.yaml` 和 `config/user.db`）
3. **切换到 Docker 部署**：套件作者的安装脚本不可控，长期建议迁到我们维护的 Docker 镜像，受 `requirements.txt` + `init-010-update` 双重防线保护

---

## 应用层启动 banner

`app/helper/setuptools_guard.py` 在启动时如果检测到环境异常，会：

1. 在 stderr 打印醒目告警块
2. 设置环境变量 `NT_SETUPTOOLS_DEGRADED=1` 与 `NT_SETUPTOOLS_DEGRADED_REASON=...`

WebUI 可以读取该变量，在设置页或首页飘红 banner 提示用户运行修复脚本。

---

## 长期改进 TODO

- [ ] 给 NasTool 套件作者提 PR / issue：`install.sh` 钉 `setuptools<70`
- [ ] 评估替换 `fast-bencode` → `bencodepy`（活跃维护，有 wheel，全 setuptools 兼容）
- [ ] 评估替换 supervisor 为纯 s6（应用层 Docker 镜像已用 s6，可彻底踢掉 supervisor 依赖）
- [ ] 上述两步完成后，setuptools 上限可以放到最新版

---

## 相关文件索引

| 文件 | 作用 |
|---|---|
| `requirements.txt` | 顶部 `pip<25` + `setuptools<70` 强约束 |
| `docker/Dockerfile` | Alpine 镜像构建钉死 |
| `docker/debian.Dockerfile` | Debian 镜像构建钉死 |
| `docker/rootfs/.../init-010-update/run` | 容器启动 hook 钉死 |
| `package/builder/Dockerfile` | PyInstaller 打包构建钉死 |
| `.github/workflows/build-package.yml` | CI 三平台 runner 钉死 |
| `app/helper/setuptools_guard.py` | 应用启动自检守门员 |
| `run.py` | 启动早期调用 guard |
