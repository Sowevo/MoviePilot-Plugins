import os
from typing import Optional, List, Tuple, Dict, Any

from sqlalchemy.orm import Session

from app.core.event import eventmanager, Event
from app.chain.transfer import TransferChain
from app.plugins import _PluginBase
from app.schemas import ManualTransferItem, FileItem
from app.schemas.types import EventType
from app.db import db_query
from app.db.models import MediaServerItem
from app.log import logger



class MediaTo115(_PluginBase):
    # 插件名称
    plugin_name = "MediaTo115"
    # 插件描述
    plugin_desc = "通过命令选择媒体文件上传到115网盘。"
    # 插件图标
    plugin_icon = ""
    # 插件版本
    plugin_version = "0.0.1"
    # 插件作者
    plugin_author = "sowevo"
    # 作者主页
    author_url = "https://github.com/sowevo"
    # 插件配置项ID前缀
    plugin_config_prefix = "mediato115_"
    # 加载顺序
    plugin_order = 30
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _media_paths = ""


    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._media_paths = config.get("media_paths") or ""

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/mediato115",
                "event": EventType.PluginAction,
                "desc": "通过命令选择媒体文件上传到115网盘。",
                "category": "",
                "data": {
                    "action": "mediato115"
                }
            }
        ]

    @eventmanager.register(EventType.PluginAction)
    def mediato115(self, event: Event = None):
        if not self._enabled:
            return

        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "mediato115":
                return

            if not self._media_paths:
                logger.info(f"未配置允许的目录")
                self.post_message(channel=event_data.get("channel"),
                                  title=f"未配置允许的目录",
                                  userid=event_data.get("user"))
                return

            args = event_data.get("arg_str")
            if not args:
                logger.info(f"缺少参数：{event_data}")
                return

            args_list = args.split(" ")
            # 检查参数数量是否正确 (1个参数)
            if len(args_list) != 1:
                logger.info(f"参数错误：{args_list}")
                self.post_message(channel=event_data.get("channel"),
                                  title=f"参数错误！ /mediato115 电影名 或 /mediato115 剧集名",
                                  userid=event_data.get("user"))
                return

            media_items = self.__get_media_by_title(title=args_list[0])
            if not media_items:
                logger.info(f"未找到媒体：{args_list[0]}")
                self.post_message(channel=event_data.get("channel"),
                                  title=f"未找到媒体信息：{args_list[0]}",
                                  userid=event_data.get("user"))
                return
            elif len(media_items) > 1:
                # 拼接媒体的名字
                # noinspection PyTypeChecker
                media_items_title = ",".join([media_item.title for media_item in media_items])

                logger.info(f"找到多个媒体：{media_items_title}")
                # 发送带有交互按钮的消息,让用户选
                self._send_main_menu(event_data,media_items)
                return

            media_item = media_items[0]
            # 上传到115
            self.__upload_to_115(media_item,event_data)

    def _send_main_menu(self, event_data, items):
        """
        发送主菜单
        """
        channel = event_data.get("channel")
        userid = event_data.get("user")
        # 遍历items的前4个,生成菜单
        menu_items = items[:4]
        # 生成菜单
        menu_buttons = []
        # 生成消息文本
        menu_text = ""
        for item in menu_items:
            menu_buttons.append({"text": menu_items.index(item) + 1, "callback_data": f"[PLUGIN]{self.__class__.__name__}|{item.item_id}"})
            menu_text += f"{menu_items.index(item) + 1}. {item.title}|{item.item_type}\n"

        buttons = [
            menu_buttons
        ]


        self.post_message(
            channel=channel,
            title="发现多个匹配项目,请选择需要上传的项目：",
            text=f"{menu_text}",
            userid=userid,
            buttons=buttons
        )

    @eventmanager.register(EventType.MessageAction)
    def message_action(self, event: Event):
        """
        处理消息按钮回调
        """
        event_data = event.event_data
        if not event_data:
            return

        # 检查是否为本插件的回调
        plugin_id = event_data.get("plugin_id")
        if plugin_id != self.__class__.__name__:
            return

        # 获取回调数据
        item_id = event_data.get("text", "")
        logger.info(f"回调数据：{item_id}")
        media_items = self.__get_media_by_item_id(item_id=item_id)
        logger.info(f"查询到媒体：{media_items}")
        if not media_items:
            logger.info(f"未找到媒体：{item_id}")
            self.post_message(channel=event_data.get("channel"),
                              title=f"未找到媒体信息：{item_id}",
                              userid=event_data.get("user"))
            return
        media_item = media_items[0]
        logger.info(f"上传媒体：{media_item.title}")
        # 上传到115
        self.__upload_to_115(media_item,event_data)


    def get_state(self) -> bool:
        return self._enabled

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            }
                        ]
                    },{
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextarea',
                                        'props': {
                                            'model': 'media_paths',
                                            'label': '允许上传的本地媒体路径',
                                            'rows': 5,
                                            'placeholder': '每一行一个目录'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                ]
            }
        ], {
            "enabled": False,
            "media_paths": "",
        }

    def get_page(self) -> Optional[List[dict]]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        pass

    @db_query
    def __get_media_by_title(self, db: Optional[Session], title: str) -> list[type[MediaServerItem]]:
        """
        根据标题查询媒体服务器媒体条目
        """
        return db.query(MediaServerItem).filter(MediaServerItem.title.ilike(f"%{title}%")).all()

    @db_query
    def __get_media_by_item_id(self, db: Optional[Session], item_id: str) -> list[type[MediaServerItem]]:
        """
        根据item_id查询媒体服务器媒体条目
        """
        logger.info(f"根据item_id查询媒体服务器媒体条目：{item_id}")
        return db.query(MediaServerItem).filter(MediaServerItem.item_id == item_id).all()


    def __upload_to_115(self, media_item, event_data):
        path = str(media_item.path)
        title = media_item.title
        item_type = media_item.item_type
        logger.info(f"找到一个媒体{title}->{path}")

        # 已选择的目录
        paths = self._media_paths.split("\n")

        # 检查文件是否在允许的目录下
        if not any(path.startswith(p) for p in paths):
            logger.info(f"文件不在允许的目录下：{path}")
            self.post_message(channel=event_data.get("channel"),
                              title=f"文件不在允许的目录下：{path}",
                              userid=event_data.get("user"))
            return

        # 检查文件是否存在
        if not os.path.exists(path):
            logger.info(f"文件不存在：{path}")
            self.post_message(channel=event_data.get("channel"),
                              title=f"文件不存在：{path}",
                              userid=event_data.get("user"))
            return

        file_root = None
        # 获取根目录
        if item_type == "电影":
            file_root = os.path.dirname(path)
        elif item_type == "电视剧":
            file_root = path

        # 拼一个ManualTransferItem
        transfer_item = ManualTransferItem(
            fileitem=FileItem(
                storage="local",
                type="dir",
                path=file_root,
                name=title,
                basename=title
            ),
            target_storage="u115",
        )

        state, errormsg = TransferChain().manual_transfer(
            fileitem=transfer_item.fileitem,
            target_storage=transfer_item.target_storage,
            target_path=transfer_item.target_path,
            background=True
        )
        if not state:
            logger.info(f"转移失败：{errormsg}")
            self.post_message(channel=event_data.get("channel"),
                              title=f"转移失败：{errormsg}",
                              userid=event_data.get("user"))
            return
        self.post_message(channel=event_data.get("channel"),
                          title=f"转移任务创建成功：{title},请稍后",
                          userid=event_data.get("user"))
