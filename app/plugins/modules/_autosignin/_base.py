# -*- coding: utf-8 -*-
import re
from abc import ABCMeta, abstractmethod
from urllib.parse import urlencode

import log
from app.utils import StringUtils


class _ISiteSigninHandler(metaclass=ABCMeta):
    """
    实现站点签到的基类，所有站点签到类都需要继承此类，并实现match和signin方法
    实现类放置到sitesignin目录下将会自动加载
    """
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = ""

    # 默认签到相对路径，子类按需覆盖（如 "/attendance.php" / "/showup.php" 等）
    # 仅在子类调用 build_sign_url() 时生效，不影响其他子类自定义实现
    _default_sign_path = ""

    @abstractmethod
    def match(self, url):
        """
        根据站点Url判断是否匹配当前站点签到类，大部分情况使用默认实现即可
        :param url: 站点Url
        :return: 是否匹配，如匹配则会调用该类的signin方法
        """
        return True if StringUtils.url_equal(url, self.site_url) else False

    @abstractmethod
    def signin(self, site_info: dict):
        """
        执行签到操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: True|False,签到结果信息
        """
        pass

    @staticmethod
    def sign_in_result(html_res, regexs):
        """
        判断是否签到成功
        """
        html_text = re.sub(r"#\d+", "", re.sub(r"\d+px", "", html_res))
        for regex in regexs:
            if re.search(str(regex), html_text):
                return True
        return False

    @staticmethod
    def normalize_params(params) -> str:
        """
        把站点 NOTE 中的 `signurl_params` 规整成 URL query 字符串（不带前导 ?）。

        支持以下输入格式：
          - dict：{"uid": "12345", "token": "abc"} → "uid=12345&token=abc"
            * value 为 None 的键会被过滤
          - str： "uid=12345"  /  "?uid=12345"  /  "&uid=12345" → "uid=12345"
          - 其他/空：返回 ""

        :param params: 任意来源的参数（通常来自 site_info["signurl_params"]）
        :return: 规整后的 query 字符串，可直接拼到 URL 后面
        """
        if not params:
            return ""
        if isinstance(params, dict):
            try:
                return urlencode({k: v for k, v in params.items() if v is not None})
            except Exception:
                return ""
        if isinstance(params, str):
            return params.strip().lstrip("?").strip("&")
        return ""

    @classmethod
    def build_sign_url(cls,
                       signurl: str,
                       signurl_params=None,
                       sign_path: str = None,
                       fallback_host: str = None) -> str:
        """
        通用签到 URL 拼接：
          base_url(取自 signurl) + sign_path + ?signurl_params

        - signurl 仅用于取 base_url（与系统其他模块取 base_url 行为一致），
          不直接当签到地址用，避免污染 signurl 作为 baseurl 的语义。
        - signurl 异常或空时回退到 fallback_host（默认 https://www.<site_url>）。
        - sign_path 默认取子类的 `_default_sign_path`。

        :param signurl: 站点 signurl 字段（可能为 None / 首页 / 含 path 或 query）
        :param signurl_params: 签到时要附加的 URL 参数（dict 或 str）
        :param sign_path: 签到相对路径，缺省取 cls._default_sign_path
        :param fallback_host: signurl 解析失败时的兜底域名
        :return: 拼好的完整签到 URL
        """
        path = sign_path if sign_path is not None else cls._default_sign_path
        base_url = StringUtils.get_base_url(signurl) if signurl else None
        if not base_url:
            base_url = fallback_host or (f"https://www.{cls.site_url}" if cls.site_url else "")

        sign_url = f"{base_url}{path}"
        query = cls.normalize_params(signurl_params)
        if query:
            sep = "&" if "?" in sign_url else "?"
            sign_url = f"{sign_url}{sep}{query}"
        return sign_url

    def info(self, msg):
        """
        记录INFO日志
        :param msg: 日志信息
        """
        log.info(f"【Sites】{self.__class__.__name__} - {msg}")

    def warn(self, msg):
        """
        记录WARN日志
        :param msg: 日志信息
        """
        log.warn(f"【Sites】{self.__class__.__name__} - {msg}")

    def error(self, msg):
        """
        记录ERROR日志
        :param msg: 日志信息
        """
        log.error(f"【Sites】{self.__class__.__name__} - {msg}")

    def debug(self, msg):
        """
        记录Debug日志
        :param msg: 日志信息
        """
        log.debug(f"【Sites】{self.__class__.__name__} - {msg}")
