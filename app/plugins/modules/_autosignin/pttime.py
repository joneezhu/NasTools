from app.plugins.modules._autosignin._base import _ISiteSigninHandler
from app.utils import StringUtils, RequestUtils
from config import Config


class PTTime(_ISiteSigninHandler):
    """
    车站签到
    支持在站点高级设置中通过 NOTE 字段添加 `signurl_params`，
    用于在签到时附加自定义 URL 参数，例如 pttime 需要 ?uid=xxx 的场景。

    signurl_params 接受以下格式：
      - 字符串： "uid=12345&token=abc"   或   "?uid=12345"
      - 字典：   {"uid": "12345"}
    """

    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "pttime.org"

    # 默认签到路径（基类的 build_sign_url 会用到）
    _default_sign_path = "/attendance.php"

    # 签到成功
    _success_text = "签到成功"
    _repeat_text = "今天已签到，请勿重复刷新"

    @classmethod
    def match(cls, url):
        """
        根据站点Url判断是否匹配当前站点签到类，大部分情况使用默认实现即可
        :param url: 站点Url
        :return: 是否匹配，如匹配则会调用该类的signin方法
        """
        return True if StringUtils.url_equal(url, cls.site_url) else False

    def signin(self, site_info: dict):
        """
        执行签到操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 签到结果信息
        """
        site = site_info.get("name")
        site_cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        proxy = Config().get_proxies() if site_info.get("proxy") else None

        # 用基类公共方法拼签到 URL：base_url(signurl) + /attendance.php + ?signurl_params
        sign_url = self.build_sign_url(
            signurl=site_info.get("signurl"),
            signurl_params=site_info.get("signurl_params"),
        )
        self.info(f"开始签到，使用 URL: {sign_url}")

        # 获取页面html
        html_res = RequestUtils(cookies=site_cookie,
                                headers=ua,
                                proxies=proxy
                                ).get_res(url=sign_url)
        if not html_res or html_res.status_code != 200:
            self.error(f"签到失败，请检查站点连通性")
            return False, f'【{site}】签到失败，请检查站点连通性'

        if "login.php" in html_res.text:
            self.error(f"签到失败，cookie失效")
            return False, f'【{site}】签到失败，cookie失效'

        # 判断是否已签到
        # '已连续签到278天，此次签到您获得了100魔力值奖励!'
        if self._success_text in html_res.text:
            self.info(f"签到成功")
            return True, f'【{site}】签到成功'
        if self._repeat_text in html_res.text:
            self.info(f"今日已签到")
            return True, f'【{site}】今日已签到'
        self.error(f"签到失败，签到接口返回 {html_res.text}")
        return False, f'【{site}】签到失败'
