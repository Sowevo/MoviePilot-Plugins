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
    plugin_name = "本地文件上传"
    # 插件描述
    plugin_desc = "通过命令选择媒体文件上传到115网盘。"
    # 插件图标
    plugin_icon = ""
    # 插件版本
    plugin_version = "0.0.3"
    # 插件作者
    plugin_author = "Sowevo"
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

            if not self._media_paths or not self._media_paths.strip():
                logger.warning("未配置允许的目录")
                self.post_message(channel=event_data.get("channel"),
                                  title="❌ 配置错误",
                                  text="请先在插件配置中设置允许上传的本地媒体路径",
                                  userid=event_data.get("user"))
                return

            args = event_data.get("arg_str")
            if not args or not args.strip():
                logger.warning("缺少参数")
                self.post_message(channel=event_data.get("channel"),
                                  title="❌ 参数错误",
                                  text="请提供媒体名称\n用法：/mediato115 电影名 或 /mediato115 剧集名",
                                  userid=event_data.get("user"))
                return

            args_list = args.strip().split(" ")
            # 检查参数数量是否正确 (1个参数)
            if len(args_list) != 1:
                logger.warning(f"参数错误：{args_list}")
                self.post_message(channel=event_data.get("channel"),
                                  title="❌ 参数错误",
                                  text="只能输入一个媒体名称\n用法：/mediato115 电影名 或 /mediato115 剧集名",
                                  userid=event_data.get("user"))
                return

            media_items = self.__get_media_by_title(title=args_list[0])
            if not media_items:
                logger.info(f"未找到媒体：{args_list[0]}")
                self.post_message(channel=event_data.get("channel"),
                                  title="❌ 未找到媒体",
                                  text=f"未找到名为「{args_list[0]}」的媒体信息\n请检查媒体名称是否正确",
                                  userid=event_data.get("user"))
                return
            elif len(media_items) > 1:
                logger.info(f"找到{len(media_items)}个匹配的媒体项目")
                # 发送带有交互按钮的消息,让用户选
                self._send_main_menu(event_data, media_items)
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
        
        # 限制显示前4个项目
        menu_items = items[:4]
        
        # 生成菜单按钮和文本
        menu_buttons = []
        menu_text_lines = []
        
        for i, item in enumerate(menu_items, 1):
            menu_buttons.append({
                "text": str(i), 
                "callback_data": f"[PLUGIN]{self.__class__.__name__}|{item.item_id}"
            })
            menu_text_lines.append(f"{i}. {item.title} ({item.item_type})")

        self.post_message(
            channel=channel,
            title="🔍 发现多个匹配项目",
            text="请选择需要上传的项目：\n" + "\n".join(menu_text_lines),
            userid=userid,
            buttons=[menu_buttons]
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
        
        # 验证item_id
        if not item_id or not item_id.strip():
            logger.warning("回调数据为空")
            self.post_message(channel=event_data.get("channel"),
                              title="❌ 数据错误",
                              text="回调数据无效",
                              userid=event_data.get("user"))
            return
            
        media_items = self.__get_media_by_item_id(item_id=item_id)
        logger.debug(f"查询到{len(media_items) if media_items else 0}个媒体项目")
        if not media_items:
            logger.warning(f"未找到媒体：{item_id}")
            self.post_message(channel=event_data.get("channel"),
                              title="❌ 未找到媒体",
                              text=f"未找到ID为「{item_id}」的媒体信息",
                              userid=event_data.get("user"))
            return
        media_item = media_items[0]
        logger.info(f"用户选择媒体：{media_item.title} ({media_item.item_type})")
        # 上传到115
        self.__upload_to_115(media_item, event_data)


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
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal'
                                        },
                                        'content': [
                                            {
                                                'component': 'div',
                                                'content': [
                                                    {
                                                        'component': 'div',
                                                        'text': '【使用方法】'
                                                    },
                                                    {
                                                        'component': 'div',
                                                        'text': '1. 在下方配置允许上传的本地媒体路径（每行一个目录）'
                                                    },
                                                    {
                                                        'component': 'div',
                                                        'text': '2. 在聊天界面使用命令：/mediato115 电影名 或 /mediato115 剧集名'
                                                    },
                                                    {
                                                        'component': 'div',
                                                        'text': '3. 系统会自动从媒体库中搜索匹配的媒体文件并上传到115网盘'
                                                    },
                                                    {
                                                        'component': 'div',
                                                        'text': '4. 如果找到多个匹配项，会显示选择菜单供您选择'
                                                    },
                                                    {
                                                        'component': 'div',
                                                        'text': '5. 只有位于配置路径下的文件才能被上传'
                                                    }
                                                ]
                                            }
                                        ]
                                    },                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal'
                                        },
                                        'content': [
                                            {
                                                'component': 'div',
                                                'content': [
                                                    {
                                                        'component': 'div',
                                                        'text': '使用本功能需要先进入 设定-目录 进行配置:'
                                                    },{
                                                        'component': 'div',
                                                        'text': '1. 添加目录配置卡,需要按照媒体类型和媒体类别,资源存储选择本地,'
                                                    },{
                                                        'component': 'div',
                                                        'props': {
                                                            'style': {
                                                                'margin-left': '20px'
                                                            }
                                                        },
                                                        'text': '资源目录输入本地媒体库路径(应该与下方配置的[允许上传的本地媒体路径]一致)'
                                                    },{
                                                        'component': 'div',
                                                        'text': '2.自动整理模式选择手动整理,媒体库存储选择115网盘,'
                                                    },{
                                                        'component': 'div',
                                                        'props': {
                                                            'style': {
                                                                'margin-left': '20px'
                                                            }
                                                        },
                                                        'text': '并配置好115网盘的目标路径,整理方式选择复制,按需配置分类,重命名通知'
                                                    },{
                                                        'component': 'div',
                                                        'props': {
                                                            'style': {
                                                                'margin-left': '20px'
                                                            }
                                                        },
                                                        'text': '本插件通过触发上面配置的目录的手动整理,实现文件上传'
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
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
        logger.debug(f"根据item_id查询媒体服务器媒体条目：{item_id}")
        return db.query(MediaServerItem).filter(MediaServerItem.item_id == item_id).all()


    def __upload_to_115(self, media_item, event_data):
        path = str(media_item.path)
        title = media_item.title
        item_type = media_item.item_type
        logger.info(f"开始处理媒体上传：{title} ({item_type}) -> {path}")
        
        # 验证媒体项目的基本信息
        if not path or not title or not item_type:
            logger.error(f"媒体信息不完整：path={path}, title={title}, item_type={item_type}")
            self.post_message(channel=event_data.get("channel"),
                              title="❌ 数据错误",
                              text="媒体信息不完整，无法上传",
                              userid=event_data.get("user"))
            return

        # 获取允许的目录列表，去除空白字符和空行
        allowed_paths = [p.strip() for p in self._media_paths.split("\n") if p.strip()]
        
        # 验证路径安全性
        if not allowed_paths:
            logger.error("没有配置允许的路径")
            self.post_message(channel=event_data.get("channel"),
                              title="❌ 配置错误",
                              text="没有配置允许上传的路径",
                              userid=event_data.get("user"))
            return

        # 检查文件是否在允许的目录下
        if not any(path.startswith(allowed_path) for allowed_path in allowed_paths):
            logger.warning(f"文件不在允许的目录下：{path}")
            self.post_message(channel=event_data.get("channel"),
                              title="❌ 路径限制",
                              text=f"文件路径不在允许的目录范围内\n文件：{path}\n请检查插件配置中的允许路径设置",
                              userid=event_data.get("user"))
            return

        # 检查文件是否存在
        if not os.path.exists(path):
            logger.warning(f"文件不存在：{path}")
            self.post_message(channel=event_data.get("channel"),
                              title="❌ 文件不存在",
                              text=f"本地文件不存在或已被删除\n文件：{path}",
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
            logger.error(f"转移失败：{errormsg}")
            self.post_message(channel=event_data.get("channel"),
                              title="❌ 上传失败",
                              text=f"文件上传到115网盘失败\n原因：{errormsg}",
                              userid=event_data.get("user"))
            return
        
        logger.info(f"转移任务创建成功：{title}")
        self.post_message(channel=event_data.get("channel"),
                          title="✅ 上传任务已创建",
                          text=f"媒体「{title}」已加入上传队列\n请稍后查看上传进度",
                          userid=event_data.get("user"))
