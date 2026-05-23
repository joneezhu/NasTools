# -*- coding: utf-8 -*-
"""
setuptools 版本守门员 (启动早期自检)
=========================================

背景:
- fast-bencode==1.1.3 是上古 sdist, 调用 distutils.parse_command_line
  setuptools 70+ 删除该 API, 安装时会爆 TypeError
- supervisor 仍 import pkg_resources
  setuptools 81+ 移除 pkg_resources, supervisor 启动即 ImportError, 群晖套件起不来
- 上游套件作者的 install.sh / update 钩子里 `pip install --upgrade setuptools`
  没有钉版本上限, 一旦自动升级到 70+/81+ 整个套件锁死

策略:
- 启动早期检测 setuptools 版本
- 若 >= 70 (硬上限) 或 pkg_resources 不可 import, 标记环境失态 (degraded)
- 不在生产路径上自动 pip 修复 (有写权限/网络/PEP 668 等问题), 仅打印明显告警
- WebUI 后续可根据 env 标志在设置页飘红 banner 提示用户 SSH 修复
- 兜底: 单纯打印 + 设置环境变量, 不阻塞主进程启动 (主进程能不能起来另说,
  起不来时这段日志会出现在套件 / docker logs, 帮助用户定位)

读取方式:
- 任何模块可通过 `os.environ.get("NT_SETUPTOOLS_DEGRADED")` 判断
- True 字符串 "1" 表示当前环境 setuptools 异常
"""

import os
import sys
import importlib

# 硬上限: setuptools 必须严格小于这个版本
# - fast-bencode 要求 <70
# - supervisor 要求 <81 (pkg_resources 在 81 被删)
# 取交集 70 是最安全的
SETUPTOOLS_MAX_MAJOR = 70

ENV_FLAG = "NT_SETUPTOOLS_DEGRADED"
ENV_REASON = "NT_SETUPTOOLS_DEGRADED_REASON"


def _mark_degraded(reason: str) -> None:
    os.environ[ENV_FLAG] = "1"
    os.environ[ENV_REASON] = reason
    sys.stderr.write(
        "\n"
        "============================================================\n"
        "[setuptools_guard] WARNING: Python 构建环境异常\n"
        "  原因: %s\n"
        "  影响: supervisor / fast-bencode / 部分老式 sdist 包可能无法正常工作\n"
        "  修复: SSH 进入容器或群晖套件目录执行:\n"
        "        python3 -m pip install --upgrade --force-reinstall \\\n"
        "          'pip<25' 'setuptools<70' wheel\n"
        "  说明: 详见 docs/troubleshooting/setuptools.md\n"
        "============================================================\n\n"
        % reason
    )


def check() -> bool:
    """
    返回 True 表示环境正常, False 表示已 degraded.
    永不抛异常, 只打印 + 设置 env flag.
    """
    try:
        # 1) setuptools 版本检测
        try:
            import setuptools  # noqa: F401
            version = getattr(setuptools, "__version__", "0")
            major = int(str(version).split(".")[0])
        except Exception as e:  # setuptools 缺失也是异常
            _mark_degraded("setuptools 无法导入: %s" % e)
            return False

        if major >= SETUPTOOLS_MAX_MAJOR:
            _mark_degraded(
                "setuptools 版本 %s >= %d, 与 fast-bencode / supervisor 不兼容"
                % (version, SETUPTOOLS_MAX_MAJOR)
            )
            return False

        # 2) pkg_resources 可 import 检测 (即使 setuptools 版本对, 也可能 site-packages 半破)
        try:
            importlib.import_module("pkg_resources")
        except Exception as e:
            _mark_degraded(
                "pkg_resources 无法导入 (setuptools 安装可能损坏): %s" % e
            )
            return False

        # 通过
        os.environ.pop(ENV_FLAG, None)
        os.environ.pop(ENV_REASON, None)
        return True

    except Exception as e:
        # 守门员自身不能影响主进程启动, 任何意外都吞掉
        _mark_degraded("自检逻辑异常 (已忽略, 不阻塞启动): %s" % e)
        return False


def is_degraded() -> bool:
    """供 WebUI 等模块查询"""
    return os.environ.get(ENV_FLAG) == "1"


def get_reason() -> str:
    return os.environ.get(ENV_REASON, "")
