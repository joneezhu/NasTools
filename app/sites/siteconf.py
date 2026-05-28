import random
import time
import re
import log
from threading import Lock

from lxml import etree

from app.helper import ChromeHelper
from app.utils import ExceptionUtils, StringUtils, RequestUtils
from app.utils.commons import singleton
from config import Config
from web.backend.pro_user import ProUser
from urllib import parse
from app.apis import MTeamApi


@singleton
class SiteConf:
    user = None
    # 页面HTML缓存: {(url, cookie, ua, render, proxy): (timestamp, html_text)}
    _page_cache = {}
    _page_cache_lock = Lock()
    # 缓存过期时间（秒）
    _PAGE_CACHE_TTL = 300
    # 站点签到支持的识别XPATH
    _SITE_CHECKIN_XPATH = [
        '//a[@id="signed"]',
        '//a[contains(@href, "attendance")]',
        '//a[contains(text(), "签到")]',
        '//a/b[contains(text(), "签 到")]',
        '//span[@id="sign_in"]/a',
        '//a[contains(@href, "addbonus")]',
        '//input[@class="dt_button"][contains(@value, "打卡")]',
        '//a[contains(@href, "sign_in")]',
        '//a[contains(@onclick, "do_signin")]',
        '//a[@id="do-attendance"]',
        '//shark-icon-button[@href="attendance.php"]'
    ]

    # 站点详情页字幕下载链接识别XPATH
    _SITE_SUBTITLE_XPATH = [
        '//td[@class="rowhead"][text()="字幕"]/following-sibling::td//a/@href',
    ]

    # 站点登录界面元素XPATH
    _SITE_LOGIN_XPATH = {
        "username": [
            '//input[@name="username"]',
            '//input[@id="form_item_username"]',
            '//input[@id="username"]'
        ],
        "password": [
            '//input[@name="password"]',
            '//input[@id="form_item_password"]',
            '//input[@id="password"]'
        ],
        "captcha": [
            '//input[@name="imagestring"]',
            '//input[@name="captcha"]',
            '//input[@id="form_item_captcha"]'
        ],
        "captcha_img": [
            '//img[@alt="CAPTCHA"]/@src',
            '//img[@alt="SECURITY CODE"]/@src',
            '//img[@id="LAY-user-get-vercode"]/@src',
            '//img[contains(@src,"/api/getCaptcha")]/@src'
        ],
        "submit": [
            '//input[@type="submit"]',
            '//button[@type="submit"]',
            '//button[@lay-filter="login"]',
            '//button[@lay-filter="formLogin"]',
            '//input[@type="button"][@value="登录"]'
        ],
        "error": [
            "//table[@class='main']//td[@class='text']/text()"
        ],
        "twostep": [
            '//input[@name="two_step_code"]',
            '//input[@name="2fa_secret"]'
        ]
    }

    def __init__(self):
        self.init_config()

    def init_config(self):
        self.user = ProUser()

    def get_checkin_conf(self):
        return self._SITE_CHECKIN_XPATH

    def get_subtitle_conf(self):
        return self._SITE_SUBTITLE_XPATH

    def get_login_conf(self):
        return self._SITE_LOGIN_XPATH

    def get_grap_conf(self, url=None):
        if not url:
            return self.user.get_brush_conf()
        for k, v in self.user.get_brush_conf().items():
            if StringUtils.url_equal(k, url):
                return v
        return {}

    def check_torrent_attr(self, torrent_url, cookie, ua=None, apikey=None, proxy=False):
        """
        检验种子是否免费，当前做种人数
        :param torrent_url: 种子的详情页面
        :param cookie: 站点的Cookie
        :param ua: 站点的ua
        :param apikey: 站点的apikey
        :param proxy: 是否使用代理
        :return: 种子属性，包含FREE 2XFREE HR PEER_COUNT等属性
        """
        ret_attr = {
            "free": False,
            "2xfree": False,
            "hr": False,
            "peer_count": 0,
            "downloadvolumefactor": 1.0,
            "uploadvolumefactor": 1.0,
        }
        if not torrent_url:
            return ret_attr
        domain = StringUtils.get_url_domain(torrent_url)
        if 'm-team' in domain:
            return MTeamApi.check_torrent_attr(torrent_url, ua, apikey, proxy)
        xpath_strs = self.get_grap_conf(torrent_url)
        if not xpath_strs:
            return ret_attr
        html_text = self.__get_site_page_html(url=torrent_url,
                                              cookie=cookie,
                                              ua=ua,
                                              render=xpath_strs.get('RENDER'),
                                              proxy=proxy)
        if not html_text:
            return ret_attr
        try:
            html = etree.HTML(html_text)
            # 检测2XFREE
            for xpath_str in xpath_strs.get("2XFREE", []):
                elements = html.xpath(xpath_str)
                if elements:
                    elem_text = ''.join(elements[0].itertext()).strip()
                    if elem_text:
                        ret_attr["free"] = True
                        ret_attr["2xfree"] = True
                        ret_attr["downloadvolumefactor"] = 0
                        ret_attr["uploadvolumefactor"] = 2.0
                        log.debug("【Brush】匹配2XFREE, xpath: %s, text: %s" % (xpath_str, elem_text[:50]))
                        break
            # 检测FREE
            for xpath_str in xpath_strs.get("FREE", []):
                elements = html.xpath(xpath_str)
                if elements:
                    elem_text = ''.join(elements[0].itertext()).strip()
                    if elem_text:
                        ret_attr["free"] = True
                        ret_attr["downloadvolumefactor"] = 0
                        ret_attr["uploadvolumefactor"] = 1.0
                        log.debug("【Brush】匹配FREE, xpath: %s, text: %s" % (xpath_str, elem_text[:50]))
                        break
            # 检测HR
            for xpath_str in xpath_strs.get("HR", []):
                if html.xpath(xpath_str):
                    ret_attr["hr"] = True
            # 检测PEER_COUNT当前做种人数
            for xpath_str in xpath_strs.get("PEER_COUNT", []):
                peer_count_dom = html.xpath(xpath_str)
                if peer_count_dom:
                    peer_count_str = ''.join(peer_count_dom[0].itertext())
                    peer_count_digit_str = ""
                    for m in peer_count_str:
                        if m.isdigit():
                            peer_count_digit_str = peer_count_digit_str + m
                        if m == " ":
                            break
                    ret_attr["peer_count"] = int(peer_count_digit_str) if len(peer_count_digit_str) > 0 else 0
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
        # 随机休眼后再返回
        time.sleep(round(random.uniform(1, 5), 1))
        return ret_attr

    @staticmethod
    def __get_site_page_html(url, cookie, ua, render=False, proxy=False):
        cache_key = (url, cookie, ua, render, proxy)
        current_time = time.time()
        # 检查缓存（带TTL过期）
        with SiteConf._page_cache_lock:
            cached = SiteConf._page_cache.get(cache_key)
            if cached:
                cached_time, cached_html = cached
                if current_time - cached_time < SiteConf._PAGE_CACHE_TTL:
                    return cached_html
                else:
                    del SiteConf._page_cache[cache_key]
        # 抓取页面
        html_text = None
        if render:
            with ChromeHelper(headless=True) as chrome:
                if chrome.get_status() and chrome.visit(url=url, cookie=cookie, ua=ua, proxy=proxy):
                    time.sleep(10)
                    html_text = chrome.get_html()
        else:
            res = RequestUtils(
                cookies=cookie,
                headers=ua,
                proxies=Config().get_proxies() if proxy else None
            ).get_res(url=url)
            if res and res.status_code == 200:
                res.encoding = res.apparent_encoding
                html_text = res.text
        # 写入缓存并清理过期条目
        if html_text:
            with SiteConf._page_cache_lock:
                SiteConf._page_cache[cache_key] = (current_time, html_text)
                # 缓存超过200条时清理过期条目
                if len(SiteConf._page_cache) > 200:
                    expired_keys = [k for k, v in SiteConf._page_cache.items()
                                    if current_time - v[0] > SiteConf._PAGE_CACHE_TTL]
                    for k in expired_keys:
                        del SiteConf._page_cache[k]
        return html_text
