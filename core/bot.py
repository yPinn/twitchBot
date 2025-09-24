import asyncio
import logging
from collections.abc import Callable
from typing import Any

import twitchio
from twitchio.ext import commands
from twitchio.web import AiohttpAdapter

from utils.message_utils import is_self_message

from .database import DatabaseManager
from .eventsub_manager import EventSubManager
from .oauth_manager import OAuthManager

logger = logging.getLogger(__name__)


class NiiBot(commands.Bot):  # type: ignore[misc]
    """簡化的 Bot 類別，專注於核心功能"""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        bot_id: str,
        owner_id: str,
        port: int,
        database_manager: DatabaseManager,
        prefix: str = "!",
    ) -> None:
        self.database = database_manager
        self.eventsub_manager = EventSubManager(self, database_manager)
        self.oauth_manager = OAuthManager(client_id, port)

        self._service_initialized = False
        self._initialization_lock = asyncio.Lock()
        self._message_handlers: list[Callable[[Any], Any]] = []
        self._channel_settings_cache: dict[str, dict[str, Any]] = {}

        super().__init__(
            client_id=client_id,
            client_secret=client_secret,
            bot_id=bot_id,
            owner_id=owner_id,
            prefix=prefix,
        )

    # ========== 核心初始化 ==========

    async def setup_hook(self) -> None:
        """設定 HTTP 適配器並初始化服務"""
        adapter = AiohttpAdapter(host="0.0.0.0", port=self.oauth_manager.port)
        await self.set_adapter(adapter)
        logger.info(f"HTTP server started on port {self.oauth_manager.port}")

        has_tokens = await self.database.check_existing_tokens()

        if has_tokens:
            await self.initialize_services()
        else:
            logger.info("First time setup - OAuth authorization required")
            self.oauth_manager.log_oauth_urls()

        await self._load_all_components()

    async def _load_all_components(self) -> None:
        """載入所有組件"""
        components = [
            "components.system_cmds",
            "components.custom_cmds",
            "components.events",
            "components.sukaoM",
            "components.translation",
            "components.be_first",
            "components.tft",
            "components.ai",
            "components.loyalty_rewards",
        ]

        loaded_count = 0
        failed_components = []

        for component in components:
            try:
                await self.load_module(component)
                loaded_count += 1
            except Exception as e:
                failed_components.append(f"{component}: {e}")

        logger.info(f"Components loaded: {loaded_count}/{len(components)}")
        if failed_components:
            logger.error(f"Failed components: {', '.join(failed_components)}")

    async def initialize_services(self) -> None:
        """統一初始化服務"""
        async with self._initialization_lock:
            if self._service_initialized:
                logger.debug("Services already initialized, skipping")
                return

            try:
                await self.ensure_default_channel()

                limits = await self.eventsub_manager.check_eventsub_limits()
                if limits.get("remaining_cost", 0) < 100:
                    logger.warning(
                        f"EventSub cost limit nearly reached: "
                        f"{limits.get('total_cost', 0)}/{limits.get('max_total_cost', 10000)}"
                    )

                await self.eventsub_manager.subscribe_all_events()
                self._service_initialized = True
                logger.info("Bot services initialized")
            except Exception as e:
                logger.error(f"Service initialization failed: {e}")
                raise

    async def ensure_default_channel(self) -> None:
        """確保預設頻道存在"""
        try:
            users = await self.fetch_users(ids=[str(self.owner_id)])
            if users:
                owner_name = users[0].name or "Unknown"
                await self.database.add_channel(
                    str(self.owner_id), owner_name, "system"
                )
                logger.info(f"Default channel configured: {owner_name}")
        except Exception as e:
            logger.error(f"Failed to initialize default channel: {e}")

    # ========== Token 管理 ==========

    async def add_token(
        self, token: str, refresh: str
    ) -> twitchio.authentication.ValidateTokenPayload:
        """儲存新的 OAuth token"""
        async with self._initialization_lock:
            was_empty = not await self.database.check_existing_tokens()

            resp: twitchio.authentication.ValidateTokenPayload = (
                await super().add_token(token, refresh)
            )

            await self.database.add_token(str(resp.user_id), token, refresh)
            logger.info("Token added: %s", resp.user_id)

            if was_empty and not self._service_initialized:
                logger.info("Initial setup completed")
                await self.initialize_services()

            return resp

    async def load_tokens(self, path: str | None = None) -> None:
        """TwitchIO 框架自動調用的 tokens 載入方法"""
        try:
            tokens = await self.database.load_tokens()
            if not tokens:
                return

            logger.info(f"Loading {len(tokens)} tokens from database")

            for token_data in tokens:
                await super().add_token(token_data["token"], token_data["refresh"])

        except Exception as e:
            logger.error(f"Failed to load tokens: {e}")

    # ========== 頻道管理 ==========

    async def get_active_channels(self) -> list[Any]:
        """取得所有啟用的頻道"""
        return await self.database.get_active_channels()

    async def add_channel(
        self, channel_id: str, channel_name: str, added_by: str | None = None
    ) -> bool:
        """新增頻道到資料庫"""
        return await self.database.add_channel(channel_id, channel_name, added_by)

    async def remove_channel(self, channel_id: str) -> bool:
        """移除頻道"""
        return await self.database.remove_channel(channel_id)

    # ========== 設定管理 ==========

    async def get_channel_settings(self, channel_id: str) -> dict[str, Any]:
        """取得頻道設定（含快取）"""
        if channel_id in self._channel_settings_cache:
            return self._channel_settings_cache[channel_id]

        settings = await self.database.get_channel_settings(channel_id)
        self._channel_settings_cache[channel_id] = settings
        return settings

    def clear_channel_settings_cache(self, channel_id: str | None = None) -> None:
        """清除頻道設定快取"""
        if channel_id:
            self._channel_settings_cache.pop(channel_id, None)
        else:
            self._channel_settings_cache.clear()

    async def is_command_enabled(self, channel_id: str, command_name: str) -> bool:
        """檢查指令是否在該頻道啟用"""
        try:
            settings = await self.get_channel_settings(channel_id)
            disabled_commands = settings.get("settings", {}).get(
                "disabled_commands", []
            )
            return command_name not in disabled_commands
        except Exception as e:
            logger.error(f"Failed to check command status: {e}")
            return True

    # ========== 自訂指令 ==========

    async def get_custom_command(
        self, channel_id: str, cmd_name: str
    ) -> dict[str, Any] | None:
        """取得自訂指令"""
        return await self.database.get_custom_command(channel_id, cmd_name)

    async def log_command_usage(
        self, channel_id: str, user_id: str, cmd_name: str
    ) -> None:
        """記錄指令使用（批次版本）"""
        await self.database.log_command_usage(channel_id, user_id, cmd_name)

    async def reload_custom_commands(self, channel_id: str) -> None:
        """重載特定頻道的自訂指令緩存"""
        try:
            custom_commands_module = self.modules.get("components.custom_cmds")
            if not custom_commands_module:
                logger.warning("Custom commands module not loaded")
                return

            if not hasattr(custom_commands_module, "_component_instance"):
                logger.warning("Custom commands module has no component instance")
                return

            component = custom_commands_module._component_instance
            if not component:
                logger.warning("Custom commands component instance is None")
                return

            if not hasattr(component, "reload_channel_commands"):
                logger.warning(
                    "Custom commands component has no reload_channel_commands method"
                )
                return

            reload_method = component.reload_channel_commands
            if not callable(reload_method):
                logger.warning("reload_channel_commands is not callable")
                return

            await reload_method(channel_id)
            logger.info(f"Reloaded custom commands for channel {channel_id}")

        except Exception as e:
            logger.error(f"Failed to reload custom commands: {e}")

    # ========== 消息處理 ==========

    def register_message_handler(self, handler: Callable[[Any], Any]) -> None:
        """註冊消息處理器"""
        self._message_handlers.append(handler)
        logger.debug(f"Registered message handler: {handler.__name__}")

    def unregister_message_handler(self, handler: Callable[[Any], Any]) -> None:
        """取消註冊消息處理器"""
        if handler in self._message_handlers:
            self._message_handlers.remove(handler)
            logger.debug(f"Unregistered message handler: {handler.__name__}")

    async def event_message(self, message: Any) -> None:
        """統一的消息處理入口"""
        if is_self_message(self, message):
            return

        try:
            # TwitchIO 3.x: 使用 message.broadcaster.id 取得頻道 ID
            channel_id = (
                str(message.broadcaster.id)
                if hasattr(message, "broadcaster") and message.broadcaster
                else self.owner_id
            )

            # 確保 channel_id 是字串類型
            if channel_id is None:
                channel_id = self.owner_id

            channel_settings = await self.get_channel_settings(channel_id)
            channel_prefix = channel_settings.get("prefix", "!")

            original_prefix = getattr(self, "_prefix", "!")
            self._prefix = channel_prefix

            try:
                content = message.text.strip()
                if content.startswith(channel_prefix):
                    command_name = content[len(channel_prefix) :].split()[0].lower()
                    if command_name and not await self.is_command_enabled(
                        channel_id, command_name
                    ):
                        logger.debug(
                            f"Command '{command_name}' is disabled in channel {channel_id}"
                        )
                        return

                await self.process_commands(message)

                for handler in self._message_handlers:
                    try:
                        await handler(message)
                    except Exception as e:
                        logger.error(f"Message handler error {handler.__name__}: {e}")

            finally:
                self._prefix = original_prefix

        except Exception as e:
            logger.error(f"Message processing error: {e}")

    # ========== 事件處理 ==========

    async def event_ready(self) -> None:
        logger.info("Bot ready - ID: %s", self.bot_id)

    async def event_command_error(self, payload: Any) -> None:
        """處理指令錯誤"""
        pass

    async def event_eventsub_websocket_welcome(self, payload: Any) -> None:
        """處理 EventSub WebSocket welcome 事件（重連後自動重訂閱）"""
        try:
            logger.debug("EventSub WebSocket welcome received")
            await self.eventsub_manager.handle_websocket_reconnect()
        except Exception as e:
            logger.error(f"Error handling WebSocket welcome: {e}")

    # ========== 清理 ==========

    async def cleanup(self) -> None:
        """清理資源"""
        try:
            await self.database.close()
            logger.info("Bot cleanup completed")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    # ========== EventSub 和 OAuth 代理方法 ==========

    async def subscribe_eventsub(
        self, channel_id: str | None = None, advanced_only: bool = False
    ) -> None:
        """代理到 EventSubManager"""
        await self.eventsub_manager.subscribe_all_events(channel_id, advanced_only)

    async def check_eventsub_limits(self) -> dict[str, int]:
        """代理到 EventSubManager"""
        return await self.eventsub_manager.check_eventsub_limits()

    def generate_oauth_url_for_channel(self, channel_name: str) -> str:
        """代理到 OAuthManager"""
        return self.oauth_manager.generate_oauth_url_for_channel(channel_name)

    async def send_oauth_invite_whisper(self, channel_name: str) -> bool:
        """代理到 OAuthManager"""
        return await self.oauth_manager.send_oauth_invite_whisper(self, channel_name)

    def generate_oauth_urls(self) -> None:
        """代理到 OAuthManager"""
        self.oauth_manager.log_oauth_urls()

    # ========== 向後兼容屬性 ==========

    @property
    def token_database(self) -> Any:
        """向後兼容：返回資料庫連接池"""
        return self.database.pool
