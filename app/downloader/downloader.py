import os
from threading import Lock
from enum import Enum
import json

from apscheduler.schedulers.background import BackgroundScheduler # type: ignore

import log
from app.conf import ModuleConf
from app.conf import SystemConfig
from app.filetransfer import FileTransfer
from app.helper import DbHelper, ThreadHelper, SubmoduleHelper
from app.media import Media
from app.media.meta import MetaInfo
from app.mediaserver import MediaServer
from app.message import Message
from app.plugins import EventManager
from app.sites import Sites, SiteSubtitle
from app.utils import Torrent, StringUtils, SystemUtils, ExceptionUtils, NumberUtils
from app.utils.commons import singleton
from app.utils.types import MediaType, DownloaderType, SearchType, RmtMode, EventType, SystemConfigKey
from app.apis import MTeamApi
from config import Config, PT_TAG, RMT_MEDIAEXT, PT_TRANSFER_INTERVAL

lock = Lock()
client_lock = Lock()


@singleton
class Downloader:
    # 客户端实例
    clients = {}

    _downloader_schema = []
    _download_order = None
    _download_settings = {}
    _downloader_confs = {}
    _monitor_downloader_ids = []
    # 下载器ID-名称枚举类
    _DownloaderEnum = None
    _scheduler = None

    message = None
    mediaserver = None
    filetransfer = None
    media = None
    sites = None
    sitesubtitle = None
    dbhelper = None
    systemconfig = None
    eventmanager = None

    def __init__(self):
        self._downloader_schema = SubmoduleHelper.import_submodules(
            'app.downloader.client',
            filter_func=lambda _, obj: hasattr(obj, 'client_id')
        )
        log.debug(f"【Downloader】加载下载器类型：{self._downloader_schema}")
        self.init_config()

    def init_config(self):
        self.dbhelper = DbHelper()
        self.message = Message()
        self.mediaserver = MediaServer()
        self.filetransfer = FileTransfer()
        self.media = Media()
        self.sites = Sites()
        self.systemconfig = SystemConfig()
        self.eventmanager = EventManager()
        self.sitesubtitle = SiteSubtitle()
        # 清空已存在下载器实例
        self.clients = {}
        # 下载器配置，生成实例
        self._downloader_confs = {}
        self._monitor_downloader_ids = []
        for downloader_conf in self.dbhelper.get_downloaders():
            if not downloader_conf:
                continue
            did = downloader_conf.ID
            name = downloader_conf.NAME
            enabled = downloader_conf.ENABLED
            # 下载器监控配置
            transfer = downloader_conf.TRANSFER
            only_nastool = downloader_conf.ONLY_NASTOOL
            match_path = downloader_conf.MATCH_PATH
            rmt_mode = downloader_conf.RMT_MODE
            rmt_mode_name = ModuleConf.RMT_MODES.get(rmt_mode).value if rmt_mode else ""
            # 输出日志
            if transfer:
                log_content = ""
                if only_nastool:
                    log_content += "启用标签隔离，"
                if match_path:
                    log_content += "启用目录隔离，"
                log.info(f"【Downloader】读取到监控下载器：{name}{log_content}转移方式：{rmt_mode_name}")
                if enabled:
                    self._monitor_downloader_ids.append(did)
                else:
                    log.info(f"【Downloader】下载器：{name} 不进行监控：下载器未启用")
            # 下载器登录配置
            config = json.loads(downloader_conf.CONFIG)
            dtype = downloader_conf.TYPE
            self._downloader_confs[str(did)] = {
                "id": did,
                "name": name,
                "type": dtype,
                "enabled": enabled,
                "transfer": transfer,
                "only_nastool": only_nastool,
                "match_path": match_path,
                "rmt_mode": rmt_mode,
                "rmt_mode_name": rmt_mode_name,
                "config": config,
                "download_dir": json.loads(downloader_conf.DOWNLOAD_DIR)
            }
        # 下载器ID-名称枚举类生成
        self._DownloaderEnum = Enum('DownloaderIdName',
                                    {did: conf.get("name") for did, conf in self._downloader_confs.items()})
        pt = Config().get_config('pt')
        if pt:
            self._download_order = pt.get("download_order")
        # 下载设置
        self._download_settings = {
            "-1": {
                "id": -1,
                "name": "预设",
                "category": '',
                "tags": PT_TAG,
                "is_paused": 0,
                "upload_limit": 0,
                "download_limit": 0,
                "ratio_limit": 0,
                "seeding_time_limit": 0,
                "downloader": "",
                "downloader_name": "",
                "downloader_type": ""
            }
        }
        download_settings = self.dbhelper.get_download_setting()
        for download_setting in download_settings:
            downloader_id = download_setting.DOWNLOADER
            download_conf = self._downloader_confs.get(str(downloader_id))
            if download_conf:
                downloader_name = download_conf.get("name")
                downloader_type = download_conf.get("type")
            else:
                downloader_name = ""
                downloader_type = ""
                downloader_id = ""
            self._download_settings[str(download_setting.ID)] = {
                "id": download_setting.ID,
                "name": download_setting.NAME,
                "category": download_setting.CATEGORY,
                "tags": download_setting.TAGS,
                "is_paused": download_setting.IS_PAUSED,
                "upload_limit": download_setting.UPLOAD_LIMIT,
                "download_limit": download_setting.DOWNLOAD_LIMIT,
                "ratio_limit": download_setting.RATIO_LIMIT / 100,
                "seeding_time_limit": download_setting.SEEDING_TIME_LIMIT,
                "downloader": downloader_id,
                "downloader_name": downloader_name,
                "downloader_type": downloader_type
            }
        # 启动下载器监控服务
        self.start_service()

    def __build_class(self, ctype, conf=None):
        for downloader_schema in self._downloader_schema:
            try:
                if downloader_schema.match(ctype):
                    return downloader_schema(conf)
            except Exception as e:
                ExceptionUtils.exception_traceback(e)
        return None

    @property
    def default_downloader_id(self):
        """
        获取默认下载器id
        """
        default_downloader_id = SystemConfig().get(SystemConfigKey.DefaultDownloader)
        if not default_downloader_id or not self.get_downloader_conf(default_downloader_id):
            default_downloader_id = ""
        return default_downloader_id

    @property
    def default_download_setting_id(self):
        """
        获取默认下载设置
        :return: 默认下载设置id
        """
        default_download_setting_id = SystemConfig().get(SystemConfigKey.DefaultDownloadSetting) or "-1"
        if not self._download_settings.get(default_download_setting_id):
            default_download_setting_id = "-1"
        return default_download_setting_id

    def get_downloader_type(self, downloader_id=None):
        """
        获取下载器的类型
        """
        if not downloader_id:
            return self.default_client.get_type()
        return self.__get_client(downloader_id).get_type()

    @property
    def default_client(self):
        """
        获取默认下载器实例
        """
        return self.__get_client(self.default_downloader_id)

    @property
    def monitor_downloader_ids(self):
        """
        获取监控下载器ID列表
        """
        return self._monitor_downloader_ids

    def start_service(self):
        """
        转移任务调度
        """
        # 移出现有任务
        self.stop_service()
        # 启动转移任务
        if not self._monitor_downloader_ids:
            return
        self._scheduler = BackgroundScheduler(timezone=Config().get_timezone())
        for downloader_id in self._monitor_downloader_ids:
            self._scheduler.add_job(func=self.transfer,
                                    args=[downloader_id],
                                    trigger='interval',
                                    seconds=PT_TRANSFER_INTERVAL)
        self._scheduler.print_jobs()
        self._scheduler.start()
        log.info("下载文件转移服务启动，目的目录：媒体库")

    def __get_client(self, did=None):
        if not did:
            return None
        downloader_conf = self.get_downloader_conf(did)
        if not downloader_conf:
            log.info("【Downloader】下载器配置不存在")
            return None
        if not downloader_conf.get("enabled"):
            log.info(f"【Downloader】下载器 {downloader_conf.get('name')} 未启用")
            return None
        ctype = downloader_conf.get("type")
        config = downloader_conf.get("config")
        config["download_dir"] = downloader_conf.get("download_dir")
        config["name"] = downloader_conf.get("name")
        with client_lock:
            if not self.clients.get(str(did)):
                self.clients[str(did)] = self.__build_class(ctype, config)
            return self.clients.get(str(did))

    def download(self,
                 media_info,
                 is_paused=None,
                 tag=None,
                 download_dir=None,
                 download_setting=None,
                 downloader_id=None,
                 upload_limit=None,
                 download_limit=None,
                 torrent_file=None,
                 in_from=None,
                 user_name=None,
                 proxy=None):
        """
        添加下载任务，根据当前使用的下载器分别调用不同的客户端处理
        :return: 下载器ID, 种子ID，错误信息
        """
        # 触发下载事件
        self.eventmanager.send_event(EventType.DownloadAdd, {
            "media_info": media_info.to_dict(),
            "is_paused": is_paused,
            "tag": tag,
            "download_dir": download_dir,
            "download_setting": download_setting,
            "downloader_id": downloader_id,
            "torrent_file": torrent_file
        })

        # 1) 解析种子内容（本地文件 / 远端 URL / m-team 兜底）
        url, content, dl_files_folder, dl_files, site_info, retmsg = \
            self.__resolve_torrent_content(media_info, torrent_file, proxy)
        if retmsg:
            log.warn("【Downloader】%s" % retmsg)
        if not content:
            self.__notify_download_fail(media_info, in_from, retmsg or "下载链接为空")
            return None, None, retmsg or "下载链接为空"

        # 2) 解析下载设置 / 选择下载器
        download_attr, downloader_id, downloader, downloader_conf, ds_err = \
            self.__resolve_download_setting(media_info, download_setting, downloader_id)
        if ds_err:
            self.__notify_download_fail(media_info, in_from, "请检查下载设置所选下载器是否有效且启用")
            return None, None, ds_err
        downloader_name = downloader_conf.get("name")
        download_setting_name = download_attr.get("name")

        try:
            # 3) 组装 add_torrent 所需参数
            params = self.__build_download_kwargs(
                media_info=media_info,
                download_attr=download_attr,
                downloader_conf=downloader_conf,
                tag=tag, is_paused=is_paused,
                download_dir=download_dir,
                upload_limit=upload_limit,
                download_limit=download_limit,
            )

            # 打印日志
            print_url = content if isinstance(content, str) else url
            log.info(f"【Downloader】下载器 {downloader_name} 添加任务{'并暂停' if params['is_paused'] else ''}："
                     f"%s，目录：%s，Url：%s"
                     % (media_info.org_string, params["download_dir"], print_url))

            # 4) 根据下载器类型调用 add_torrent
            ret, download_id = self.__add_to_client(
                downloader=downloader, content=content, site_info=site_info, params=params)

            if not ret:
                # 4.1) add 失败兜底：可能是种子已存在，按 in_from(订阅/刷流) 分流处理
                action, dl_id, retmsg = self.__handle_existing_on_add_fail(
                    media_info=media_info,
                    downloader_id=downloader_id,
                    downloader_name=downloader_name,
                    params=params,
                    in_from=in_from,
                    torrent_file=torrent_file,
                )
                if action == "ok":
                    log.info(f"【Downloader】{downloader_name} 种子已存在并按现有任务处理完成："
                             f"{media_info.org_string}")
                    return downloader_id, dl_id, ""
                if action == "fail":
                    # 已落过滤表，下次跳过；通知 + 返回失败
                    self.__notify_download_fail(media_info, in_from, retmsg)
                    return downloader_id, None, retmsg
                # action == "unknown"：未识别为已存在，沿用旧失败返回
                self.__notify_download_fail(media_info, in_from, "请检查下载任务是否已存在")
                return downloader_id, None, f"下载器 {downloader_name} 添加下载任务失败，请检查下载任务是否已存在"

            # 5) 善后：登记历史 / 字幕 / 消息
            self.__post_download_actions(
                media_info=media_info, downloader_id=downloader_id,
                download_id=download_id, download_dir=params["download_dir"],
                dl_files_folder=dl_files_folder, dl_files=dl_files,
                site_info=site_info, in_from=in_from, user_name=user_name,
                download_setting_name=download_setting_name,
                downloader_name=downloader_name,
            )
            return downloader_id, download_id, ""
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            self.__notify_download_fail(media_info, in_from, str(e))
            log.error(f"【Downloader】下载器 {downloader_name} 添加任务出错：%s" % str(e))
            return None, None, str(e)

    # =============== download 内部辅助 ===============

    def __notify_download_fail(self, media_info, in_from, msg):
        """触发下载失败事件并按需发消息"""
        self.eventmanager.send_event(EventType.DownloadFail, {
            "media_info": media_info.to_dict(),
            "reason": msg
        })
        if in_from:
            self.message.send_download_fail_message(media_info, f"添加下载任务失败：{msg}")

    # =============== "种子已存在" 分流处理 ===============

    def __handle_existing_on_add_fail(self, media_info, downloader_id,
                                       downloader_name, params, in_from, torrent_file):
        """
        add_torrent 失败兜底：判断种子是否已经在下载器中；若是，则按 in_from（订阅/刷流）分流处理：
        - 目录、标签、集数都一致 → ok（视为成功）
        - 目录相同，标签不同 → 追加标签 → ok
        - 目录相同（订阅+剧集且集数不同）→ 追加集数 → ok
        - 目录不同 → 视为来源不一致，失败 + 写"过滤存量表"让下次跳过
        :return: (action, dl_id, retmsg)，action ∈ {"ok","fail","unknown"}
        """
        # 仅订阅/刷流路径才走分流；其它(手动等)沿用旧失败返回
        if in_from not in (SearchType.RSS, SearchType.BRUSH):
            return "unknown", None, ""
        existed_hash = self.__resolve_existing_download_id(
            item=media_info, torrent_file=torrent_file, downloader_id=downloader_id)
        if not existed_hash:
            return "unknown", None, ""
        log.info(f"【Downloader】{downloader_name} 检测到种子已存在于下载器（hash={existed_hash}），"
                 f"开始按 {in_from.value if hasattr(in_from, 'value') else in_from} 路径分流处理")
        return self.__handle_existing_torrent(
            media_info=media_info,
            downloader_id=downloader_id,
            downloader_name=downloader_name,
            existed_hash=existed_hash,
            params=params,
            in_from=in_from,
        )

    def __handle_existing_torrent(self, media_info, downloader_id, downloader_name,
                                   existed_hash, params, in_from):
        """
        对已存在的种子按"目录/标签/集数"对比已存在任务，分别返回 ok / 追加 / 失败
        """
        client = self.__get_client(downloader_id)
        if not client:
            return "fail", None, "下载器未连接，无法处理已存在种子"
        brief = client.get_torrent_brief(existed_hash) if hasattr(client, "get_torrent_brief") else None
        if not brief:
            return "fail", None, "种子已存在但读取已存在任务信息失败"

        # 目录比较：normpath 严格相等
        target_dir = params.get("download_dir") or ""
        existing_dir = brief.get("save_path") or ""
        same_dir = bool(target_dir) and bool(existing_dir) \
                   and os.path.normpath(target_dir) == os.path.normpath(existing_dir)

        # 标签集合
        new_tags = {t for t in (params.get("tags") or []) if t}
        existing_tags = brief.get("tags") or set()

        # 集数（仅订阅 + 剧集 才考虑）
        need_eps = []
        try:
            need_eps = media_info.get_episode_list() or []
        except Exception:
            need_eps = []
        is_tv_eps = (in_from == SearchType.RSS
                     and getattr(media_info, "type", None) == MediaType.TV
                     and bool(need_eps))

        if not same_dir:
            # 目录不一致 → 失败 + 落过滤存量表
            from_label = "刷流/手动" if in_from == SearchType.RSS else "订阅/手动"
            log.warn(f"【Downloader】{downloader_name} 种子已存在但保存目录不一致："
                     f"目标={target_dir} 已存在={existing_dir}，按 {in_from.value} 来源不匹配处理")
            self.__record_existing_filter(
                media_info=media_info,
                downloader_id=downloader_id,
                existed_hash=existed_hash,
                in_from=in_from,
            )
            retmsg = (f"种子已存在于其它下载任务（来源：{from_label}），"
                      f"目录不一致：{existing_dir}，请手动转移目录后重新下载；"
                      f"已记录该种子，后续将自动跳过")
            return "fail", None, retmsg

        # 目录一致，按需追加 tag
        missing_tags = list(new_tags - existing_tags)
        if missing_tags:
            try:
                if hasattr(client, "add_torrent_tags"):
                    client.add_torrent_tags(existed_hash, missing_tags)
                    log.info(f"【Downloader】{downloader_name} 已对已存在种子追加标签："
                             f"{missing_tags} (hash={existed_hash})")
            except Exception as err:
                ExceptionUtils.exception_traceback(err)
                log.warn(f"【Downloader】{downloader_name} 追加标签出错：{str(err)}")

        # 仅订阅 + 剧集才追加缺失集
        if is_tv_eps:
            try:
                newly_selected, already_selected = self.set_files_status_append(
                    tid=existed_hash, need_episodes=need_eps, downloader_id=downloader_id)
                if newly_selected:
                    log.info(f"【Downloader】{downloader_name} 已对已存在种子追加集数："
                             f"{sorted(newly_selected)} (hash={existed_hash})")
                    # 新追加文件需要把任务启动
                    try:
                        self.start_torrents(ids=existed_hash, downloader_id=downloader_id)
                    except Exception:
                        pass
                else:
                    log.info(f"【Downloader】{downloader_name} 目标集均已选中，无需追加："
                             f"已选 {sorted(already_selected)}")
            except Exception as err:
                ExceptionUtils.exception_traceback(err)
                log.warn(f"【Downloader】{downloader_name} 追加集数出错：{str(err)}")

        return "ok", existed_hash, ""

    def __record_existing_filter(self, media_info, downloader_id, existed_hash, in_from):
        """
        把"目录不一致的已存在种子"记录到对应的过滤存量表，下次自动跳过
        - 订阅：写 RSS_TORRENTS（按 ENCLOSURE 命中跳过）
        - 刷流：写 SITE_BRUSH_TORRENTS（按 (task_id,title,enclosure) 三联命中跳过）
        - 通用：写 DOWNLOAD_HISTORY 备查
        """
        try:
            enclosure = getattr(media_info, "enclosure", None) or ""
            title = getattr(media_info, "org_string", None) or getattr(media_info, "title", "") or ""
            if in_from == SearchType.RSS:
                try:
                    from app.helper import RssHelper
                    RssHelper().simple_insert_rss_torrents(title=title, enclosure=enclosure)
                except Exception as err:
                    log.debug(f"【Downloader】写入 RSS_TORRENTS 过滤记录失败：{str(err)}")
            elif in_from == SearchType.BRUSH:
                brush_id = getattr(media_info, "brush_task_id", None)
                if brush_id:
                    try:
                        size = getattr(media_info, "size", 0) or 0
                        # download_id 用占位 "0" 避免被当作有效种子参与刷流删除/统计
                        self.dbhelper.insert_brushtask_torrent(
                            brush_id=brush_id,
                            title=title,
                            enclosure=enclosure,
                            downloader=str(downloader_id) if downloader_id is not None else "",
                            download_id="0",
                            size=size,
                        )
                    except Exception as err:
                        log.debug(f"【Downloader】写入 SITE_BRUSH_TORRENTS 过滤记录失败：{str(err)}")
            # 通用：DOWNLOAD_HISTORY 备查（save_dir 标记为已存在以便排查）
            try:
                self.dbhelper.insert_download_history(
                    media_info=media_info,
                    downloader=str(downloader_id) if downloader_id is not None else "",
                    download_id=existed_hash,
                    save_dir="(existing)",
                )
            except Exception as err:
                log.debug(f"【Downloader】写入 DOWNLOAD_HISTORY 失败：{str(err)}")
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            log.warn(f"【Downloader】记录已存在过滤项异常：{str(err)}")

    def __resolve_torrent_content(self, media_info, torrent_file, proxy):
        """
        拿到种子内容：优先本地 .torrent 文件，否则按 enclosure URL 下载（含 m-team 兜底、magnet 直返）
        :return: (url, content, dl_files_folder, dl_files, site_info, retmsg)
        """
        site_info, dl_files_folder, dl_files, retmsg = {}, "", [], ""
        page_url = media_info.page_url

        if torrent_file:
            url = os.path.basename(torrent_file)
            content, dl_files_folder, dl_files, retmsg = Torrent().read_torrent_content(torrent_file)
            return url, content, dl_files_folder, dl_files, site_info, retmsg

        # 拿不到 enclosure 时尝试 m-team 详情页
        url = media_info.enclosure
        # 防御：上游若把 .torrent bytes 直接塞进 enclosure（历史 bug，参见 Torrent.format_enclosure 注释），
        # 这里强制丢弃并走 __ensure_enclosure 兜底，避免后续 url.startswith 类型异常。
        if isinstance(url, (bytes, bytearray)):
            log.warn("【Downloader】enclosure 不是 URL 字符串而是 bytes，已丢弃由兜底逻辑重新解析；"
                     "可能是上游 format_enclosure/类似入口塞错值")
            media_info.enclosure = ""
            url = ""
        if not url:
            self.__ensure_enclosure(media_info)
            url = media_info.enclosure
        if not url:
            return None, None, "", [], site_info, "下载链接为空"

        # 磁力链直返
        if url.startswith("magnet:"):
            return url, url, "", [], site_info, ""

        site_info = self.sites.get_sites(siteurl=url)
        _, content, dl_files_folder, dl_files, retmsg = Torrent().get_torrent_info(
            url=url,
            cookie=site_info.get("cookie"),
            ua=site_info.get("ua"),
            apikey=site_info.get("apikey"),
            referer=page_url if site_info.get("referer") else None,
            proxy=proxy if proxy is not None else site_info.get("proxy"),
        )
        return url, content, dl_files_folder, dl_files, site_info, retmsg

    def __resolve_download_setting(self, media_info, download_setting, downloader_id):
        """
        解析下载设置 + 选择下载器
        :return: (download_attr, downloader_id, downloader, downloader_conf, err_msg)
        """
        # 选下载设置
        if not download_setting and media_info.site:
            download_setting = self.sites.get_site_download_setting(media_info.site)
        if download_setting == "-2":
            download_attr = {}
        elif download_setting:
            download_attr = self.get_download_setting(download_setting) \
                            or self.get_download_setting(self.default_download_setting_id)
        else:
            download_attr = self.get_download_setting(self.default_download_setting_id)

        # 选下载器
        if not downloader_id:
            downloader_id = download_attr.get("downloader")
        downloader_conf = self.get_downloader_conf(downloader_id)
        downloader = self.__get_client(downloader_id)
        if not downloader or not downloader_conf:
            return download_attr, downloader_id, None, None, \
                   f"下载设置 {download_attr.get('name')} 所选下载器失效"
        return download_attr, downloader_id, downloader, downloader_conf, None

    def __build_download_kwargs(self, media_info, download_attr, downloader_conf,
                                tag, is_paused, download_dir, upload_limit, download_limit):
        """
        合并所有 add_torrent 调用所需参数
        """
        # 合并 tags：下载设置中的 + 调用方传入的 + 站点 tag
        tags = []
        ds_tags = download_attr.get("tags")
        if ds_tags:
            tags = str(ds_tags).split(";")
        if tag:
            tags.extend(tag if isinstance(tag, list) else [tag])
        site_tags = self.sites.get_site_download_tags(media_info.site)
        if site_tags:
            tags.extend(str(site_tags).split(";"))

        # 是否暂停
        if is_paused is None:
            is_paused = StringUtils.to_bool(download_attr.get("is_paused"))
        else:
            is_paused = bool(is_paused)

        # 速度限制
        upload_limit = upload_limit or download_attr.get("upload_limit")
        download_limit = download_limit or download_attr.get("download_limit")

        # 下载目录与分类
        category = download_attr.get("category")
        if not download_dir:
            download_info = self.__get_download_dir_info(media_info, downloader_conf.get("download_dir"))
            download_dir = download_info.get("path")
            if not category:
                category = download_info.get("category")

        return {
            "tags": tags,
            "category": category,
            "is_paused": is_paused,
            "download_dir": download_dir,
            "upload_limit": upload_limit,
            "download_limit": download_limit,
            "ratio_limit": download_attr.get("ratio_limit"),
            "seeding_time_limit": download_attr.get("seeding_time_limit"),
        }

    def __add_to_client(self, downloader, content, site_info, params):
        """
        按下载器类型调用 add_torrent
        :return: (ret, download_id)
        """
        downloader_type = downloader.get_type()
        tags = params["tags"]

        if downloader_type == DownloaderType.TR:
            ret = downloader.add_torrent(
                content,
                is_paused=params["is_paused"],
                download_dir=params["download_dir"],
                cookie=site_info.get("cookie"))
            if not ret:
                return None, None
            download_id = ret.hashString
            downloader.change_torrent(
                tid=download_id, tag=tags,
                upload_limit=params["upload_limit"],
                download_limit=params["download_limit"],
                ratio_limit=params["ratio_limit"],
                seeding_time_limit=params["seeding_time_limit"])
            return ret, download_id

        if downloader_type == DownloaderType.QB:
            # 优先从 .torrent / magnet 内容直接计算 v1 infohash，作为 download_id（0 等待，且对"种子已存在"场景同样生效）
            info_hash = None
            try:
                info_hash = downloader.compute_torrent_hash(content)
            except Exception as e:
                log.debug(f"【Downloader】计算 infohash 异常：{str(e)}")
                info_hash = None
            ret = downloader.add_torrent(
                content,
                is_paused=params["is_paused"],
                download_dir=params["download_dir"],
                tag=tags,
                category=params["category"],
                content_layout="Original",
                upload_limit=params["upload_limit"],
                download_limit=params["download_limit"],
                ratio_limit=params["ratio_limit"],
                seeding_time_limit=params["seeding_time_limit"],
                cookie=site_info.get("cookie"))
            if not ret:
                return None, None
            # 1) hash 已知：直接当 download_id（覆盖正常加种 / 已存在 / Conflict409 三种场景）
            if info_hash:
                # 短轮询确认 qb 中可见（多数情况下立即可见，最多兜底 10s）
                download_id = downloader.get_torrent_id_by_hash(info_hash) or info_hash
                return ret, download_id
            # 2) 极端兜底：hash 解析失败时（罕见，例如非标准 .torrent / 网络 url 未下载到内容）
            #    上层 __resolve_existing_download_id 会再尝试从 enclosure / page_url 解析 hash 兜底
            log.warn(f"【Downloader】QB 加种成功但未能解析 infohash，download_id 留空交由上层兜底解析")
            return ret, None

        # 其它下载器
        ret = downloader.add_torrent(
            content,
            is_paused=params["is_paused"],
            tag=tags,
            download_dir=params["download_dir"],
            category=params["category"])
        return ret, ret

    def __post_download_actions(self, media_info, downloader_id, download_id,
                                download_dir, dl_files_folder, dl_files,
                                site_info, in_from, user_name,
                                download_setting_name, downloader_name):
        """
        下载成功后的善后：保存目录推算 + 登记历史 + 下字幕 + 发消息
        """
        # 推算保存目录与字幕目录
        save_dir = subtitle_dir = None
        visit_dir = self.get_download_visit_dir(download_dir)
        if visit_dir:
            if dl_files_folder:
                save_dir = os.path.join(visit_dir, dl_files_folder)
                subtitle_dir = save_dir
            elif dl_files:
                save_dir = os.path.join(visit_dir, dl_files[0])
                subtitle_dir = visit_dir
            else:
                subtitle_dir = visit_dir

        # 登记下载历史
        self.dbhelper.insert_download_history(
            media_info=media_info,
            downloader=downloader_id,
            download_id=download_id,
            save_dir=save_dir)

        # 字幕
        page_url = media_info.page_url
        if page_url and subtitle_dir and site_info and site_info.get("subtitle"):
            ThreadHelper().start_thread(
                self.sitesubtitle.download,
                (media_info, site_info.get("id"), site_info.get("cookie"),
                 site_info.get("ua"), site_info.get("apikey"), subtitle_dir),
            )

        # 通知
        if in_from:
            media_info.user_name = user_name
            self.message.send_download_message(
                in_from=in_from,
                can_item=media_info,
                download_setting_name=download_setting_name,
                downloader_name=downloader_name)

    def transfer(self, downloader_id=None):
        """
        转移下载完成的文件，进行文件识别重命名到媒体库目录
        """
        downloader_ids = [downloader_id] if downloader_id else self._monitor_downloader_ids
        for did in downloader_ids:
            with lock:
                self.__transfer_for_downloader(did)

    def __transfer_for_downloader(self, downloader_id):
        """
        对单个下载器执行转移
        """
        downloader_conf = self.get_downloader_conf(downloader_id)
        if not downloader_conf:
            return
        name = downloader_conf.get("name")
        only_nastool = downloader_conf.get("only_nastool")
        match_path = downloader_conf.get("match_path")
        rmt_mode = ModuleConf.RMT_MODES.get(downloader_conf.get("rmt_mode"))
        _client = self.__get_client(downloader_id)
        if not _client:
            return
        trans_tasks = _client.get_transfer_task(
            tag=PT_TAG if only_nastool else None, match_path=match_path)
        if not trans_tasks:
            return
        log.info(f"【Downloader】下载器 {name} 开始转移下载文件...")
        for task in trans_tasks:
            done_flag, done_msg = self.filetransfer.transfer_media(
                in_from=self._DownloaderEnum[str(downloader_id)],
                in_path=task.get("path"),
                rmt_mode=rmt_mode)
            if not done_flag:
                log.warn(f"【Downloader】下载器 {name} 任务%s 转移失败：%s"
                         % (task.get("path"), done_msg))
                _client.set_torrents_status(ids=task.get("id"), tags=task.get("tags"))
                continue
            # 转移成功
            if rmt_mode in [RmtMode.MOVE, RmtMode.RCLONE, RmtMode.MINIO]:
                log.warn(f"【Downloader】下载器 {name} 移动模式下删除种子文件：%s" % task.get("id"))
                _client.delete_torrents(delete_file=True, ids=task.get("id"))
            else:
                _client.set_torrents_status(ids=task.get("id"), tags=task.get("tags"))
        log.info(f"【Downloader】下载器 {name} 下载文件转移结束")

    def get_torrents(self, downloader_id=None, ids=None, tag=None):
        """
        获取种子信息
        :param downloader_id: 下载器ID
        :param ids: 种子ID
        :param tag: 种子标签
        :return: 种子信息列表
        """
        if not downloader_id:
            downloader_id = self.default_downloader_id
        _client = self.__get_client(downloader_id)
        if not _client:
            return None
        try:
            torrents, error_flag = _client.get_torrents(tag=tag, ids=ids)
            if error_flag:
                return None
            return torrents
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return None

    def get_remove_torrents(self, downloader_id=None, config=None):
        """
        查询符合删种策略的种子信息
        :return: 符合删种策略的种子信息列表
        """
        if not config or not downloader_id:
            return []
        _client = self.__get_client(downloader_id)
        if not _client:
            return []
        config["filter_tags"] = config["tags"] + ([PT_TAG] if config.get("onlynastool") else [])
        torrents = _client.get_remove_torrents(config=config)
        torrents.sort(key=lambda x: x.get("name"))
        return torrents

    def get_downloading_torrents(self, downloader_id=None, ids=None, tag=None):
        """
        查询正在下载中的种子信息
        :return: 下载器名称，发生错误时返回None
        """
        if not downloader_id:
            downloader_id = self.default_downloader_id
        _client = self.__get_client(downloader_id)
        if not _client:
            return None
        try:
            return _client.get_downloading_torrents(tag=tag, ids=ids)
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return None

    def get_downloading_progress(self, downloader_id=None, ids=None, force_list=False):
        """
        查询正在下载中的进度信息
        """
        if not downloader_id:
            downloader_id = self.default_downloader_id
        _client = self.__get_client(downloader_id)
        if not _client:
            return []
        downloader_conf = self.get_downloader_conf(downloader_id)
        only_nastool = downloader_conf.get("only_nastool") if not force_list else False
        tag = [PT_TAG] if only_nastool else None
        return _client.get_downloading_progress(tag=tag, ids=ids)

    def get_completed_torrents(self, downloader_id=None, ids=None, tag=None):
        """
        查询下载完成的种子列表
        :param downloader_id: 下载器ID
        :param ids: 种子ID列表
        :param tag: 种子标签
        :return: 种子信息列表，发生错误时返回None
        """
        if not downloader_id:
            downloader_id = self.default_downloader_id
        _client = self.__get_client(downloader_id)
        if not _client:
            return None
        return _client.get_completed_torrents(ids=ids, tag=tag)

    def start_torrents(self, downloader_id=None, ids=None):
        """
        下载控制：开始
        :param downloader_id: 下载器ID
        :param ids: 种子ID列表
        :return: 处理状态
        """
        if not ids:
            return False
        _client = self.__get_client(downloader_id) if downloader_id else self.default_client
        if not _client:
            return False
        return _client.start_torrents(ids)

    def stop_torrents(self, downloader_id=None, ids=None):
        """
        下载控制：停止
        :param downloader_id: 下载器ID
        :param ids: 种子ID列表
        :return: 处理状态
        """
        if not ids:
            return False
        _client = self.__get_client(downloader_id) if downloader_id else self.default_client
        if not _client:
            return False
        return _client.stop_torrents(ids)

    def delete_torrents(self, downloader_id=None, ids=None, delete_file=False):
        """
        删除种子
        :param downloader_id: 下载器ID
        :param ids: 种子ID列表
        :param delete_file: 是否删除文件
        :return: 处理状态
        """
        if not ids:
            return False
        _client = self.__get_client(downloader_id) if downloader_id else self.default_client
        if not _client:
            return False
        return _client.delete_torrents(delete_file=delete_file, ids=ids)

    def batch_download(self,
                       in_from: SearchType,
                       media_list: list,
                       need_tvs: dict = None,
                       user_name=None):
        """
        根据命中的种子媒体信息，添加下载，由RSS或Searcher调用
        :param in_from: 来源
        :param media_list: 命中并已经识别好的媒体信息列表，包括名称、年份、季、集等信息
        :param need_tvs: 缺失的剧集清单，对于剧集只有在该清单中的季和集才会下载，对于电影无需输入该参数
        :param user_name: 用户名称
        :return: 已经添加了下载的媒体信息表表、剩余未下载到的媒体信息
        """
        # 已下载的项目
        return_items = []
        # 返回按季、集数倒序排序的列表
        download_list = Torrent().get_download_list(media_list, self._download_order)

        # 构造一个上下文对象（dict），打包所有跨阶段共享的状态与回调，避免再嵌套一堆闭包
        ctx = self.__build_batch_ctx(
            in_from=in_from,
            user_name=user_name,
            need_tvs=need_tvs,
            return_items=return_items,
        )

        # ① 电影：直接下载（顺便补齐 enclosure）
        self.__dispatch_movies(download_list, ctx)

        # ② 电视剧整季匹配
        if need_tvs:
            self.__dispatch_full_seasons(download_list, ctx)

        # ③ 电视剧季内的集匹配（种子集 ⊆ 需求集 → 整体下载）
        if need_tvs:
            self.__dispatch_episodes_in_season(download_list, ctx)

        # ④ 整季中选择性下载（种子集 ∩ 需求集 > 0 → 仅勾选需要的文件，仅 QB/TR）
        if need_tvs:
            self.__dispatch_select_files_in_pack(download_list, ctx)

        # 返回下载的资源，剩下没下完的
        return return_items, need_tvs

    # =============== batch_download 内部辅助 ===============

    def __build_batch_ctx(self, in_from, user_name, need_tvs, return_items):
        """
        组装 batch_download 各阶段共享的上下文（含若干回调），避免到处定义闭包
        """
        def _download(download_item, torrent_file=None, tag=None, is_paused=None):
            _downloader_id, did, _ = self.download(
                media_info=download_item,
                download_dir=download_item.save_path,
                download_setting=download_item.download_setting,
                torrent_file=torrent_file,
                tag=tag,
                is_paused=is_paused,
                in_from=in_from,
                user_name=user_name)
            if did and download_item not in return_items:
                return_items.append(download_item)
            return _downloader_id, did

        def _update_seasons(tmdbid, need, current):
            need = list(set(need).difference(set(current)))
            for cur in current:
                for nt in need_tvs.get(tmdbid):
                    if cur == nt.get("season") or (cur == 1 and not nt.get("season")):
                        need_tvs[tmdbid].remove(nt)
            if not need_tvs.get(tmdbid):
                need_tvs.pop(tmdbid)
            return need

        def _update_episodes(tmdbid, seq, need, current):
            need = list(set(need).difference(set(current)))
            if need:
                need_tvs[tmdbid][seq]["episodes"] = need
            else:
                need_tvs[tmdbid].pop(seq)
                if not need_tvs.get(tmdbid):
                    need_tvs.pop(tmdbid)
            return need

        def _get_season_episodes(tmdbid, season):
            if not need_tvs.get(tmdbid):
                return 0
            for nt in need_tvs.get(tmdbid):
                if season == nt.get("season"):
                    return nt.get("total_episodes")
            return 0

        return {
            "need_tvs": need_tvs,
            "return_items": return_items,
            "download": _download,
            "update_seasons": _update_seasons,
            "update_episodes": _update_episodes,
            "get_season_episodes": _get_season_episodes,
        }

    def __ensure_enclosure(self, item):
        """
        没有 enclosure 时尝试从 m-team 详情页拿
        """
        if item.enclosure:
            return
        base_url = StringUtils.get_base_url(item.page_url)
        log.info(f"【Downloader】下载器检查馒头下载地址：%s" % item.page_url)
        if "m-team" in base_url:
            site_info = self.sites.get_sites_by_url_domain(base_url)
            item.enclosure = MTeamApi.get_torrent_url_by_detail_url(base_url, item.page_url, site_info)

    def __dispatch_movies(self, download_list, ctx):
        """
        电影：补齐 enclosure 后直接下载
        """
        for item in download_list:
            self.__ensure_enclosure(item)
            if item.type == MediaType.MOVIE:
                ctx["download"](item)

    def __dispatch_full_seasons(self, download_list, ctx):
        """
        电视剧整季匹配：抓"整季缺失"的需求，找含整季的种子直接下载
        """
        need_tvs = ctx["need_tvs"]
        # 收集整季缺失（episodes 为空）的需求 {tmdbid: [season,...]}
        need_seasons = {}
        for need_tmdbid, need_tv in need_tvs.items():
            for tv in need_tv:
                if not tv or tv.get("episodes"):
                    continue
                need_seasons.setdefault(need_tmdbid, []).append(tv.get("season") or 1)

        for need_tmdbid, need_season in need_seasons.items():
            for item in download_list:
                if item.type == MediaType.MOVIE:
                    continue
                if item.get_episode_list():
                    continue
                if item.tmdb_id != need_tmdbid:
                    continue
                item_season = item.get_season_list()
                if not set(item_season).issubset(set(need_season)):
                    continue
                # 单季种子：可能命名错误，鉴别下实际集数
                if len(item_season) == 1:
                    torrent_episodes, torrent_path = self.get_torrent_episodes(
                        url=item.enclosure, page_url=item.page_url)
                    season_total = ctx["get_season_episodes"](need_tmdbid, item_season[0])
                    if torrent_episodes and len(torrent_episodes) < season_total:
                        log.info(f"【Downloader】种子 {item.org_string} 未含集数信息，解析文件数为 {len(torrent_episodes)}")
                        continue
                    _, download_id = ctx["download"](download_item=item, torrent_file=torrent_path)
                else:
                    _, download_id = ctx["download"](item)
                if download_id:
                    need_season = ctx["update_seasons"](
                        tmdbid=need_tmdbid, need=need_season, current=item_season)

    def __dispatch_episodes_in_season(self, download_list, ctx):
        """
        季内集匹配：种子集是需求集的子集时，整种子下载
        """
        need_tvs = ctx["need_tvs"]
        return_items = ctx["return_items"]
        for need_tmdbid in list(need_tvs):
            need_tv = need_tvs.get(need_tmdbid)
            if not need_tv:
                continue
            for index, tv in enumerate(need_tv):
                need_season = tv.get("season") or 1
                need_episodes = tv.get("episodes") or list(range(1, tv.get("total_episodes") + 1))
                for item in download_list:
                    if item.type == MediaType.MOVIE or item in return_items:
                        continue
                    if item.tmdb_id != need_tmdbid:
                        continue
                    item_season = item.get_season_list()
                    if len(item_season) != 1 or item_season[0] != need_season:
                        continue
                    # 标题副标题没集数时，打开种子文件查
                    item_episodes = item.get_episode_list()
                    if not item_episodes:
                        torrent_episodes, _ = self.get_torrent_episodes(
                            url=item.enclosure, page_url=item.page_url)
                        if not torrent_episodes:
                            continue
                        item_episodes = torrent_episodes
                    # 种子集是需求集的子集才整体下载
                    if not set(item_episodes).issubset(set(need_episodes)):
                        continue
                    _, download_id = ctx["download"](item)
                    if download_id:
                        need_episodes = ctx["update_episodes"](
                            tmdbid=need_tmdbid, need=need_episodes,
                            seq=index, current=item_episodes)

    def __dispatch_select_files_in_pack(self, download_list, ctx):
        """
        整季合集中选择性下载：种子集 ∩ 需求集 > 0 时，暂停加入并按文件勾选目标集（仅 QB/TR）
        """
        need_tvs = ctx["need_tvs"]
        return_items = ctx["return_items"]
        for need_tmdbid in list(need_tvs):
            need_tv = need_tvs.get(need_tmdbid)
            if not need_tv:
                continue
            for index, tv in enumerate(need_tv):
                need_season = tv.get("season") or 1
                need_episodes = tv.get("episodes")
                if not need_episodes:
                    continue
                for item in download_list:
                    if item.type == MediaType.MOVIE or item in return_items:
                        continue
                    if not need_episodes:
                        break
                    if item.tmdb_id != need_tmdbid:
                        continue
                    if len(item.get_season_list()) != 1 or item.get_season_list()[0] != need_season:
                        continue
                    item_eps = item.get_episode_list()
                    if item_eps and not set(item_eps).intersection(set(need_episodes)):
                        continue
                    # 处理单个候选种子
                    new_need = self.__handle_pack_candidate(
                        item=item, index=index, need_tmdbid=need_tmdbid,
                        need_episodes=need_episodes, ctx=ctx)
                    if new_need is not None:
                        need_episodes = new_need

    def __handle_pack_candidate(self, item, index, need_tmdbid, need_episodes, ctx):
        """
        处理"合集种子选文件"的单个候选；返回更新后的 need_episodes，None 表示未处理（跳过）
        """
        # 1) 看种子里有没有需要的集
        torrent_episodes, torrent_path = self.get_torrent_episodes(
            url=item.enclosure, page_url=item.page_url)
        selected_episodes = set(torrent_episodes).intersection(set(need_episodes))
        if not selected_episodes:
            log.info("【Downloader】%s 没有需要的集，跳过..." % item.org_string)
            return None

        # 2) 加入下载（暂停态），失败时尝试用 infohash 反查老种子
        downloader_id, download_id = ctx["download"](
            download_item=item, torrent_file=torrent_path, is_paused=True)
        existed_in_downloader = False
        if not download_id:
            download_id = self.__resolve_existing_download_id(
                item=item, torrent_file=torrent_path, downloader_id=downloader_id)
            if download_id:
                existed_in_downloader = True
                log.info("【Downloader】%s 种子已存在于下载器，复用任务ID：%s"
                         % (item.org_string, download_id))
        if not download_id:
            return None

        # 3) 以"追加"方式勾选目标文件（不覆盖已有的勾选）
        log.info("【Downloader】从 %s 中选取集：%s" % (item.org_string, selected_episodes))
        newly_selected, already_selected = self.set_files_status_append(
            tid=download_id, need_episodes=selected_episodes, downloader_id=downloader_id)

        # 4) 真实命中的集 = 已选 ∪ 新追加；为空说明文件名识别不出集，做兜底
        real_hit_episodes = list(set(already_selected).union(set(newly_selected)))
        if not real_hit_episodes:
            log.warn("【Downloader】%s 未能识别种子内文件的集信息，未选中任何文件，跳过该种子"
                     % item.org_string)
            # 新加的暂停种子也启动一下，避免卡 paused
            if not existed_in_downloader:
                self.start_torrents(ids=download_id, downloader_id=downloader_id)
            return None

        # 5) 用真实命中集更新需求
        new_need = ctx["update_episodes"](
            tmdbid=need_tmdbid, need=need_episodes, seq=index, current=real_hit_episodes)

        # 6) 决定是否启动任务
        self.__start_pack_task(
            item=item, download_id=download_id, downloader_id=downloader_id,
            existed_in_downloader=existed_in_downloader,
            newly_selected=newly_selected, already_selected=already_selected)

        # 记录下载项
        ctx["return_items"].append(item)
        return new_need

    def __start_pack_task(self, item, download_id, downloader_id,
                          existed_in_downloader, newly_selected, already_selected):
        """
        合集选择性下载场景下，根据"老/新种子 + 是否有新追加文件"决定是否 start
        """
        if already_selected:
            log.info("【Downloader】%s 已选中下载的集：%s"
                     % (item.org_string, sorted(already_selected)))
        if newly_selected:
            log.info("【Downloader】%s 本次新追加的集：%s"
                     % (item.org_string, sorted(newly_selected)))
            log.info("【Downloader】%s 开始下载 " % item.org_string)
            self.start_torrents(ids=download_id, downloader_id=downloader_id)
        elif not existed_in_downloader:
            # 没有新追加，但任务是本次新加的暂停态，也得 start
            log.info("【Downloader】%s 目标集均已选中下载，启动新加暂停任务" % item.org_string)
            self.start_torrents(ids=download_id, downloader_id=downloader_id)
        else:
            log.info("【Downloader】%s 目标集对应文件均已选中下载，无需重新开始任务" % item.org_string)

    def check_exists_medias(self, meta_info, no_exists=None, total_ep=None):
        """
        检查媒体库，查询是否存在，对于剧集同时返回不存在的季集信息
        :param meta_info: 已识别的媒体信息，包括标题、年份、季、集信息
        :param no_exists: 在调用该方法前已经存储的不存在的季集信息，有传入时该函数搜索的内容将会叠加后输出
        :param total_ep: 各季的总集数
        :return: 当前媒体是否缺失，各标题总的季集和缺失的季集，需要发送的消息
        """
        if not no_exists:
            no_exists = {}
        if not total_ep:
            total_ep = {}
        # 查找的季
        if not meta_info.begin_season:
            search_season = None
        else:
            search_season = meta_info.get_season_list()
        # 查找的集
        search_episode = meta_info.get_episode_list()
        if search_episode and not search_season:
            search_season = [1]

        # 返回的消息列表
        message_list = []
        if meta_info.type != MediaType.MOVIE:
            # 是否存在的标志
            return_flag = False
            # 搜索电视剧的信息
            tv_info = self.media.get_tmdb_info(mtype=MediaType.TV, tmdbid=meta_info.tmdb_id)
            if tv_info:
                # 传入检查季
                total_seasons = []
                if search_season:
                    for season in search_season:
                        if total_ep.get(season):
                            episode_num = total_ep.get(season)
                        else:
                            episode_num = self.media.get_tmdb_season_episodes_num(tv_info=tv_info, season=season)
                        if not episode_num:
                            log.info("【Downloader】%s 第%s季 不存在" % (meta_info.get_title_string(), season))
                            message_list.append("%s 第%s季 不存在" % (meta_info.get_title_string(), season))
                            continue
                        total_seasons.append({"season_number": season, "episode_count": episode_num})
                        log.info(
                            "【Downloader】%s 第%s季 共有 %s 集" % (meta_info.get_title_string(), season, episode_num))
                else:
                    # 共有多少季，每季有多少季
                    total_seasons = self.media.get_tmdb_tv_seasons(tv_info=tv_info)
                    log.info(
                        "【Downloader】%s %s 共有 %s 季" % (
                            meta_info.type.value, meta_info.get_title_string(), len(total_seasons)))
                    message_list.append(
                        "%s %s 共有 %s 季" % (meta_info.type.value, meta_info.get_title_string(), len(total_seasons)))
                # 没有得到总季数时，返回None
                if not total_seasons:
                    return_flag = None
                else:
                    # 查询缺少多少集
                    for season in total_seasons:
                        season_number = season.get("season_number")
                        episode_count = season.get("episode_count")
                        if not season_number or not episode_count:
                            continue
                        # 检查Emby
                        no_exists_episodes = self.mediaserver.get_no_exists_episodes(meta_info,
                                                                                     season_number,
                                                                                     episode_count)
                        # 没有配置Emby
                        if no_exists_episodes is None:
                            no_exists_episodes = self.filetransfer.get_no_exists_medias(meta_info,
                                                                                        season_number,
                                                                                        episode_count)
                        if no_exists_episodes:
                            # 排序
                            no_exists_episodes.sort()
                            # 缺失集初始化
                            if not no_exists.get(meta_info.tmdb_id):
                                no_exists[meta_info.tmdb_id] = []
                            # 缺失集提示文本
                            exists_tvs_str = "、".join(["%s" % tv for tv in no_exists_episodes])
                            # 存入总缺失集
                            if len(no_exists_episodes) >= episode_count:
                                no_item = {"season": season_number, "episodes": [], "total_episodes": episode_count}
                                log.info(
                                    "【Downloader】%s 第%s季 缺失 %s 集" % (
                                        meta_info.get_title_string(), season_number, episode_count))
                                if search_season:
                                    message_list.append(
                                        "%s 第%s季 缺失 %s 集" % (meta_info.title, season_number, episode_count))
                                else:
                                    message_list.append("第%s季 缺失 %s 集" % (season_number, episode_count))
                            else:
                                no_item = {"season": season_number, "episodes": no_exists_episodes,
                                           "total_episodes": episode_count}
                                log.info(
                                    "【Downloader】%s 第%s季 缺失集：%s" % (
                                        meta_info.get_title_string(), season_number, exists_tvs_str))
                                if search_season:
                                    message_list.append(
                                        "%s 第%s季 缺失集：%s" % (meta_info.title, season_number, exists_tvs_str))
                                else:
                                    message_list.append("第%s季 缺失集：%s" % (season_number, exists_tvs_str))
                            if no_item not in no_exists.get(meta_info.tmdb_id):
                                no_exists[meta_info.tmdb_id].append(no_item)
                            # 输入检查集
                            if search_episode:
                                # 有集数，肯定只有一季
                                if not set(search_episode).intersection(set(no_exists_episodes)):
                                    # 搜索的跟不存在的没有交集，说明都存在了
                                    msg = f"媒体库中已存在剧集：\n" \
                                          f" • {meta_info.get_title_string()} {meta_info.get_season_episode_string()}"
                                    log.info(f"【Downloader】{msg}")
                                    message_list.append(msg)
                                    return_flag = True
                                    break
                        else:
                            log.info("【Downloader】%s 第%s季 共%s集 已全部存在" % (
                                meta_info.get_title_string(), season_number, episode_count))
                            if search_season:
                                message_list.append(
                                    "%s 第%s季 共%s集 已全部存在" % (meta_info.title, season_number, episode_count))
                            else:
                                message_list.append(
                                    "第%s季 共%s集 已全部存在" % (season_number, episode_count))
            else:
                log.info("【Downloader】%s 无法查询到媒体详细信息" % meta_info.get_title_string())
                message_list.append("%s 无法查询到媒体详细信息" % meta_info.get_title_string())
                return_flag = None
            # 全部存在
            if return_flag is False and not no_exists.get(meta_info.tmdb_id):
                return_flag = True
            # 返回
            return return_flag, no_exists, message_list
        # 检查电影
        else:
            exists_movies = self.mediaserver.get_movies(meta_info.title, meta_info.year)
            if exists_movies is None:
                exists_movies = self.filetransfer.get_no_exists_medias(meta_info)
            if exists_movies:
                movies_str = "\n • ".join(["%s (%s)" % (m.get('title'), m.get('year')) for m in exists_movies])
                msg = f"媒体库中已存在电影：\n • {movies_str}"
                log.info(f"【Downloader】{msg}")
                message_list.append(msg)
                return True, {}, message_list
            return False, {}, message_list

    def get_files(self, tid, downloader_id=None):
        """
        获取种子文件列表
        """
        # 客户端
        _client = self.__get_client(downloader_id) if downloader_id else self.default_client
        if not _client:
            return []
        # 种子文件
        torrent_files = _client.get_files(tid)
        if not torrent_files:
            return []

        ret_files = []
        if _client.get_type() == DownloaderType.TR:
            for file_id, torrent_file in enumerate(torrent_files):
                ret_files.append({
                    "id": file_id,
                    "name": torrent_file.name
                })
        elif _client.get_type() == DownloaderType.QB:
            for torrent_file in torrent_files:
                ret_files.append({
                    "id": torrent_file.get("index"),
                    "name": torrent_file.get("name")
                })

        return ret_files

    def set_files_status(self, tid, need_episodes, downloader_id=None):
        """
        设置文件下载状态，选中需要下载的季集对应的文件下载，其余不下载
        :param tid: 种子的hash或id
        :param need_episodes: 需要下载的文件的集信息
        :param downloader_id: 下载器ID
        :return: 返回选中的集的列表
        """
        sucess_epidised = []

        # 客户端
        if not downloader_id:
            downloader_id = self.default_downloader_id
        _client = self.__get_client(downloader_id)
        downloader_conf = self.get_downloader_conf(downloader_id)
        if not _client:
            return []
        # 种子文件
        torrent_files = self.get_files(tid=tid, downloader_id=downloader_id)
        if not torrent_files:
            return []
        if downloader_conf.get("type") == "transmission":
            files_info = {}
            for torrent_file in torrent_files:
                file_id = torrent_file.get("id")
                file_name = torrent_file.get("name")
                meta_info = MetaInfo(file_name)
                if not meta_info.get_episode_list():
                    selected = False
                else:
                    selected = set(meta_info.get_episode_list()).issubset(set(need_episodes))
                    if selected:
                        sucess_epidised = list(set(sucess_epidised).union(set(meta_info.get_episode_list())))
                if not files_info.get(tid):
                    files_info[tid] = {file_id: {'priority': 'normal', 'selected': selected}}
                else:
                    files_info[tid][file_id] = {'priority': 'normal', 'selected': selected}
            if sucess_epidised and files_info:
                _client.set_files(file_info=files_info)
        elif downloader_conf.get("type") == "qbittorrent":
            file_ids = []
            for torrent_file in torrent_files:
                file_id = torrent_file.get("id")
                file_name = torrent_file.get("name")
                meta_info = MetaInfo(file_name)
                if not meta_info.get_episode_list() or not set(meta_info.get_episode_list()).issubset(
                        set(need_episodes)):
                    file_ids.append(file_id)
                else:
                    sucess_epidised = list(set(sucess_epidised).union(set(meta_info.get_episode_list())))
            if sucess_epidised and file_ids:
                _client.set_files(torrent_hash=tid, file_ids=file_ids, priority=0)
        return sucess_epidised

    def __get_torrent_files_with_priority(self, tid, downloader_id=None):
        """
        获取种子文件列表，并附带 priority / selected 信息（用于"追加而非覆盖"场景）。
        返回结构统一为：[{"id": file_id, "name": file_name, "selected": bool}, ...]
        - QB: priority == 0 视为未选下载
        - TR: file 自身有 selected 字段
        """
        if not downloader_id:
            downloader_id = self.default_downloader_id
        _client = self.__get_client(downloader_id)
        downloader_conf = self.get_downloader_conf(downloader_id)
        if not _client or not downloader_conf:
            return []
        try:
            raw_files = _client.get_files(tid)
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return []
        if not raw_files:
            return []
        ret = []
        dtype = downloader_conf.get("type")
        if dtype == "qbittorrent":
            for f in raw_files:
                priority = f.get("priority")
                ret.append({
                    "id": f.get("index"),
                    "name": f.get("name"),
                    "selected": (priority is not None and int(priority) > 0)
                })
        elif dtype == "transmission":
            # transmissionrpc 返回的 file 是含 .selected/.name/.priority 的 namedtuple/dict
            for fid, f in enumerate(raw_files):
                # 兼容 dict 与对象两种形式
                if isinstance(f, dict):
                    selected = bool(f.get("selected", True))
                    name = f.get("name")
                else:
                    selected = bool(getattr(f, "selected", True))
                    name = getattr(f, "name", None)
                ret.append({
                    "id": fid,
                    "name": name,
                    "selected": selected
                })
        else:
            # 其它下载器暂不支持"追加"语义，回退为"全部视为已选"
            for f in raw_files:
                ret.append({
                    "id": f.get("id") if isinstance(f, dict) else None,
                    "name": f.get("name") if isinstance(f, dict) else None,
                    "selected": True
                })
        return ret

    def set_files_status_append(self, tid, need_episodes, downloader_id=None):
        """
        以"追加"方式选中需要下载的集对应文件：只把目标集对应的文件 priority 设为下载，
        不会动其它已经选中的文件。适用于"种子已存在、之前已选过部分集"的场景。
        :param tid: 种子的hash或id
        :param need_episodes: 本次需要下载的集（可迭代）
        :param downloader_id: 下载器ID
        :return: (newly_selected_episodes, already_selected_episodes)
                 newly_selected_episodes：本次实际新追加为下载的集列表
                 already_selected_episodes：本次目标集中之前就已经选中下载的集列表
        """
        newly_selected_episodes = []
        already_selected_episodes = []
        if not need_episodes:
            return newly_selected_episodes, already_selected_episodes

        if not downloader_id:
            downloader_id = self.default_downloader_id
        _client = self.__get_client(downloader_id)
        downloader_conf = self.get_downloader_conf(downloader_id)
        if not _client or not downloader_conf:
            return newly_selected_episodes, already_selected_episodes

        torrent_files = self.__get_torrent_files_with_priority(tid=tid, downloader_id=downloader_id)
        if not torrent_files:
            return newly_selected_episodes, already_selected_episodes

        need_set = set(need_episodes)
        dtype = downloader_conf.get("type")

        if dtype == "qbittorrent":
            # 仅收集"目标集对应"且"当前未选"的 file_id，把它们 priority 设为 1（normal），其他文件不动
            file_ids_to_enable = []
            for tf in torrent_files:
                file_id = tf.get("id")
                file_name = tf.get("name")
                already_selected = tf.get("selected")
                meta_info = MetaInfo(file_name) if file_name else None
                ep_list = meta_info.get_episode_list() if meta_info else []
                if not ep_list:
                    continue
                ep_set = set(ep_list)
                # 该文件覆盖的集必须是本次目标集的子集才追加（避免引入用户没要的集）
                if not ep_set.issubset(need_set):
                    continue
                if already_selected:
                    already_selected_episodes = list(set(already_selected_episodes).union(ep_set))
                else:
                    file_ids_to_enable.append(file_id)
                    newly_selected_episodes = list(set(newly_selected_episodes).union(ep_set))
            if file_ids_to_enable:
                _client.set_files(torrent_hash=tid, file_ids=file_ids_to_enable, priority=1)
        elif dtype == "transmission":
            # transmission 走 set_files(file_info)：只把"目标集对应且未选"的文件标记 selected=True，
            # 其它文件不出现在 file_info 里（不会被覆盖）
            files_info = {tid: {}}
            for tf in torrent_files:
                file_id = tf.get("id")
                file_name = tf.get("name")
                already_selected = tf.get("selected")
                meta_info = MetaInfo(file_name) if file_name else None
                ep_list = meta_info.get_episode_list() if meta_info else []
                if not ep_list:
                    continue
                ep_set = set(ep_list)
                if not ep_set.issubset(need_set):
                    continue
                if already_selected:
                    already_selected_episodes = list(set(already_selected_episodes).union(ep_set))
                else:
                    files_info[tid][file_id] = {'priority': 'normal', 'selected': True}
                    newly_selected_episodes = list(set(newly_selected_episodes).union(ep_set))
            if files_info[tid]:
                _client.set_files(file_info=files_info)
        else:
            log.warn(f"【Downloader】下载器类型 {dtype} 暂不支持文件追加选择")

        return newly_selected_episodes, already_selected_episodes

    def __resolve_existing_download_id(self, item, torrent_file=None, downloader_id=None):
        """
        当 add_torrent 未能返回 download_id 时，尝试从 item 的种子文件或下载链接中
        解析出 infohash，再到下载器中反查是否已存在该种子。
        命中则返回该种子的 hash，否则返回 None。
        仅对 QB 下载器生效（TR 由 transmissionrpc 库自身保障返回 hashString，理论上不会进入此兜底）。
        """
        try:
            if not downloader_id:
                downloader_id = self.default_downloader_id
            _client = self.__get_client(downloader_id)
            downloader_conf = self.get_downloader_conf(downloader_id)
            if not _client or not downloader_conf:
                return None
            if downloader_conf.get("type") != "qbittorrent":
                return None

            info_hash = None
            # 1) 从本地种子文件解析 infohash（最准）
            if torrent_file and os.path.exists(torrent_file):
                try:
                    import hashlib
                    from bencode import bdecode, bencode # type: ignore
                    with open(torrent_file, "rb") as f:
                        torrent_dict = bdecode(f.read())
                    if torrent_dict and "info" in torrent_dict:
                        info_hash = hashlib.sha1(bencode(torrent_dict["info"])).hexdigest().lower()
                except Exception as parse_err:
                    log.debug(f"【Downloader】解析种子文件 infohash 失败：{str(parse_err)}")
                    info_hash = None
            # 2) 从 enclosure / page_url 中粗暴抽 40 位 hex
            if not info_hash:
                import re as _re
                for u in [getattr(item, "enclosure", None), getattr(item, "page_url", None)]:
                    if not u:
                        continue
                    m = _re.search(r"([0-9a-fA-F]{40})", str(u))
                    if m:
                        info_hash = m.group(1).lower()
                        break
            if not info_hash:
                return None
            torrents = self.get_torrents(downloader_id=downloader_id, ids=info_hash)
            if torrents:
                # qb 返回的是带 .hash 字段的对象
                first = torrents[0]
                if isinstance(first, dict):
                    return first.get("hash") or info_hash
                return getattr(first, "hash", info_hash)
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
        return None

    def get_download_dirs(self, setting=None):
        """
        返回下载器中设置的保存目录
        """
        if not setting:
            setting = self.default_download_setting_id
        # 查询下载设置
        download_setting = self.get_download_setting(sid=setting)
        downloader_conf = self.get_downloader_conf(download_setting.get("downloader"))
        if not downloader_conf:
            return []
        downloaddir = downloader_conf.get("download_dir")
        # 查询目录
        save_path_list = [attr.get("save_path") for attr in downloaddir if attr.get("save_path")]
        save_path_list.sort()
        return list(set(save_path_list))

    def get_download_visit_dirs(self):
        """
        返回所有下载器中设置的访问目录
        """
        download_dirs = []
        for downloader_conf in self.get_downloader_conf().values():
            download_dirs += downloader_conf.get("download_dir")
        visit_path_list = [attr.get("container_path") or attr.get("save_path") for attr in download_dirs if
                           attr.get("save_path")]
        visit_path_list.sort()
        return list(set(visit_path_list))

    def get_download_visit_dir(self, download_dir, downloader_id=None):
        """
        返回下载器中设置的访问目录
        """
        if not downloader_id:
            downloader_id = self.default_downloader_id
        downloader_conf = self.get_downloader_conf(downloader_id)
        _client = self.__get_client(downloader_id)
        if not _client:
            return ""
        true_path, _ = _client.get_replace_path(download_dir, downloader_conf.get("download_dir"))
        return true_path

    @staticmethod
    def __get_download_dir_info(media, downloaddir):
        """
        根据媒体信息读取一个下载目录的信息
        """
        if media:
            for attr in downloaddir or []:
                if not attr:
                    continue
                if attr.get("type") and attr.get("type") != media.type.value:
                    continue
                if attr.get("category") and attr.get("category") != media.category:
                    continue
                if not attr.get("save_path") and not attr.get("label"):
                    continue
                if (attr.get("container_path") or attr.get("save_path")) \
                        and os.path.exists(attr.get("container_path") or attr.get("save_path")) \
                        and media.size \
                        and SystemUtils.get_free_space(
                    attr.get("container_path") or attr.get("save_path")
                ) < NumberUtils.get_size_gb(
                    StringUtils.num_filesize(media.size)
                ):
                    continue
                return {
                    "path": attr.get("save_path"),
                    "category": attr.get("label")
                }
        return {"path": None, "category": None}

    @staticmethod
    def __get_client_type(type_name):
        """
        根据名称返回下载器类型
        """
        if not type_name:
            return None
        for dict_type in DownloaderType:
            if dict_type.name == type_name or dict_type.value == type_name:
                return dict_type

    def get_torrent_episodes(self, url, page_url=None):
        """
        解析种子文件，获取集数
        :return: 集数列表、种子路径
        """
        if not url and page_url:
            base_url = StringUtils.get_base_url(page_url)
            log.info(f"【Downloader】检查馒头下载地址：%s" % (page_url))
            if "m-team" in base_url:
                site_info = self.sites.get_sites_by_url_domain(base_url)
                url = MTeamApi.get_torrent_url_by_detail_url(base_url, page_url, site_info)
        site_info = self.sites.get_sites(siteurl=url)
        # 保存种子文件
        file_path, _, _, files, retmsg = Torrent().get_torrent_info(
            url=url,
            cookie=site_info.get("cookie"),
            ua=site_info.get("ua"),
            apikey=site_info.get("apikey"),
            referer=page_url if site_info.get("referer") else None,
            proxy=site_info.get("proxy")
        )
        if not files:
            log.error("【Downloader】读取种子文件集数出错：%s" % retmsg)
            return [], None
        episodes = []
        for file in files:
            if os.path.splitext(file)[-1] not in RMT_MEDIAEXT:
                continue
            meta = MetaInfo(file)
            if not meta.begin_episode:
                continue
            episodes = list(set(episodes).union(set(meta.get_episode_list())))
        return episodes, file_path

    def get_download_setting(self, sid=None):
        """
        获取下载设置
        :return: 下载设置
        """
        # 更新预设
        preset_downloader_conf = self.get_downloader_conf(self.default_downloader_id)
        if preset_downloader_conf:
            self._download_settings["-1"]["downloader"] = self.default_downloader_id
            self._download_settings["-1"]["downloader_name"] = preset_downloader_conf.get("name")
            self._download_settings["-1"]["downloader_type"] = preset_downloader_conf.get("type")
        if not sid:
            return self._download_settings
        return self._download_settings.get(str(sid)) or {}

    def set_speed_limit(self, downloader_id=None, download_limit=None, upload_limit=None):
        """
        设置速度限制
        :param downloader_id: 下载器ID
        :param download_limit: 下载速度限制，单位KB/s
        :param upload_limit: 上传速度限制，单位kB/s
        """
        if not downloader_id:
            return
        _client = self.__get_client(downloader_id)
        if not _client:
            return
        try:
            download_limit = int(download_limit) if download_limit else 0
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            download_limit = 0
        try:
            upload_limit = int(upload_limit) if upload_limit else 0
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            upload_limit = 0
        _client.set_speed_limit(download_limit=download_limit, upload_limit=upload_limit)

    def get_downloader_conf(self, did=None):
        """
        获取下载器配置
        """
        if not did:
            return self._downloader_confs
        return self._downloader_confs.get(str(did))

    def get_downloader_conf_simple(self):
        """
        获取简化下载器配置
        """
        ret_dict = {}
        for downloader_conf in self.get_downloader_conf().values():
            ret_dict[str(downloader_conf.get("id"))] = {
                "id": downloader_conf.get("id"),
                "name": downloader_conf.get("name"),
                "type": downloader_conf.get("type"),
                "enabled": downloader_conf.get("enabled"),
            }
        return ret_dict

    def get_downloader(self, downloader_id=None):
        """
        获取下载器实例
        """
        if not downloader_id:
            return self.default_client
        return self.__get_client(downloader_id)

    def get_status(self, dtype=None, config=None):
        """
        测试下载器状态
        """
        if not config or not dtype:
            return False
        # 测试状态
        download_client = self.__build_class(ctype=dtype, conf=config)
        state = download_client.get_status() if download_client else False
        if not state:
            log.error(f"【Downloader】下载器连接测试失败")
        return state

    def recheck_torrents(self, downloader_id=None, ids=None):
        """
        下载控制：重新校验种子
        :param downloader_id: 下载器ID
        :param ids: 种子ID列表
        :return: 处理状态
        """
        if not ids:
            return False
        _client = self.__get_client(downloader_id) if downloader_id else self.default_client
        if not _client:
            return False
        return _client.recheck_torrents(ids)

    def stop_service(self):
        """
        停止服务
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            print(str(e))

    def get_download_history(self, date=None, hid=None, num=30, page=1):
        """
        获取下载历史记录
        """
        return self.dbhelper.get_download_history(date=date, hid=hid, num=num, page=page)

    def get_download_history_by_title(self, title):
        """
        根据标题查询下载历史记录
        :return:
        """
        return self.dbhelper.get_download_history_by_title(title=title) or []

    def get_download_history_by_downloader(self, downloader, download_id):
        """
        根据下载器和下载ID查询下载历史记录
        :return:
        """
        return self.dbhelper.get_download_history_by_downloader(downloader=downloader,
                                                                download_id=download_id)

    def update_downloader(self,
                          did,
                          name,
                          enabled,
                          dtype,
                          transfer,
                          only_nastool,
                          match_path,
                          rmt_mode,
                          config,
                          download_dir):
        """
        更新下载器
        """
        ret = self.dbhelper.update_downloader(
            did=did,
            name=name,
            enabled=enabled,
            dtype=dtype,
            transfer=transfer,
            only_nastool=only_nastool,
            match_path=match_path,
            rmt_mode=rmt_mode,
            config=config,
            download_dir=download_dir
        )
        self.init_config()
        return ret

    def delete_downloader(self, did):
        """
        删除下载器
        """
        ret = self.dbhelper.delete_downloader(did=did)
        self.init_config()
        return ret

    def check_downloader(self, did=None, transfer=None, only_nastool=None, enabled=None, match_path=None):
        """
        检查下载器
        """
        ret = self.dbhelper.check_downloader(did=did,
                                             transfer=transfer,
                                             only_nastool=only_nastool,
                                             enabled=enabled,
                                             match_path=match_path)
        self.init_config()
        return ret

    def delete_download_setting(self, sid):
        """
        删除下载设置
        """
        ret = self.dbhelper.delete_download_setting(sid=sid)
        self.init_config()
        return ret

    def update_download_setting(self,
                                sid,
                                name,
                                category,
                                tags,
                                is_paused,
                                upload_limit,
                                download_limit,
                                ratio_limit,
                                seeding_time_limit,
                                downloader):
        """
        更新下载设置
        """
        ret = self.dbhelper.update_download_setting(
            sid=sid,
            name=name,
            category=category,
            tags=tags,
            is_paused=is_paused,
            upload_limit=upload_limit,
            download_limit=download_limit,
            ratio_limit=ratio_limit,
            seeding_time_limit=seeding_time_limit,
            downloader=downloader
        )
        self.init_config()
        return ret
