import asyncio
import logging
import time
from datetime import datetime
from typing import Any

from twitchio.ext import commands

from utils.message_utils import is_self_message

logger = logging.getLogger(__name__)

# 全局組件實例引用
_component_instance: "CustomCommands | None" = None


class FakeContext:
    """輕量級 Context 實現，避免每次重新定義類別"""

    def __init__(self, bot: Any, message: Any, prefix: str) -> None:
        self.bot = bot  # 必須的 bot 屬性
        self.broadcaster = message.broadcaster
        self.chatter = message.chatter
        self.channel = message.broadcaster  # channel 是 broadcaster 的別名
        self.message = message
        self.prefix = prefix

    async def send(self, text: str, **kwargs: Any) -> None:
        await self.broadcaster.send_message(
            sender=self.bot.bot_id, message=str(text), **kwargs
        )

    async def reply(self, text: str) -> None:
        # 使用和其他組件相同的 context hack 方法
        try:
            original_text = self.message.text
            self.message.text = "!_custom_reply"
            ctx = self.bot.get_context(self.message)
            self.message.text = original_text

            if ctx and hasattr(ctx, "reply"):
                await ctx.reply(text)
            else:
                # 回退到 @ 格式
                await self.broadcaster.send_message(
                    sender=self.bot.bot_id, message=f"@{self.chatter.name} {text}"
                )

        except Exception:
            # 回退到 @ 格式
            await self.broadcaster.send_message(
                sender=self.bot.bot_id, message=f"@{self.chatter.name} {text}"
            )


class CustomCommands(commands.Component):  # type: ignore[misc]
    def __init__(self, bot: Any) -> None:
        self.bot = bot
        # 按頻道分組的指令緩存 {channel_id: {cmd_name: cmd_data}}
        self.channel_commands: dict[str, dict[str, dict[str, Any]]] = {}
        # 頻道前綴緩存 {channel_id: prefix}
        self.channel_prefixes: dict[str, str] = {}
        # 記憶體冷卻緩存 {(channel_id, user_id, cmd_name): last_used_timestamp}
        self.command_cooldowns: dict[tuple[str, str, str], float] = {}
        # 緩存時間戳 {channel_id: last_update_time}
        self.cache_timestamps: dict[str, float] = {}
        # 緩存過期時間（秒）
        self.cache_ttl = 300  # 5 分鐘
        self.loaded = False

    async def load_all_commands(self) -> None:
        """啟動時載入所有頻道的自訂指令"""
        try:
            logger.info("Loading custom commands for all channels...")

            # 先清空緩存
            self.channel_commands.clear()
            self.channel_prefixes.clear()

            # 取得所有啟用的頻道
            active_channels = await self.bot.get_active_channels()

            for channel in active_channels:
                channel_id = channel["channel_id"]
                channel_name = channel["channel_name"]

                async with self.bot.token_database.acquire() as connection:
                    # 載入該頻道的所有自訂指令
                    cmd_rows = await connection.fetch(
                        """SELECT command_name, response_text, cooldown_seconds, user_level, usage_count, created_at
                           FROM custom_commands 
                           WHERE channel_id = $1 AND is_active = true""",
                        channel_id,
                    )

                    # 載入頻道前綴設定
                    settings_row = await connection.fetchrow(
                        "SELECT prefix FROM channel_settings WHERE channel_id = $1",
                        channel_id,
                    )

                # 初始化頻道指令字典
                self.channel_commands[channel_id] = {}
                for row in cmd_rows:
                    cmd_name = row["command_name"]
                    self.channel_commands[channel_id][cmd_name] = dict(row)

                # 設定頻道前綴緩存
                self.channel_prefixes[channel_id] = (
                    settings_row["prefix"] if settings_row else "!"
                )

                # 設定快取時間戳
                self.cache_timestamps[channel_id] = time.time()

                logger.info(
                    f"Loaded {len(cmd_rows)} custom commands for channel {channel_name}, prefix: {self.channel_prefixes[channel_id]}"
                )

            self.loaded = True
            logger.info(f"Loaded custom commands for {len(active_channels)} channels")

        except Exception as e:
            logger.error(f"Failed to load custom commands: {e}")

    def get_channel_command(
        self, channel_id: str, cmd_name: str
    ) -> dict[str, Any] | None:
        """從記憶體中取得頻道的自訂指令（含過期檢查）"""
        if not self.loaded:
            return None

        # 檢查緩存是否過期或不存在
        if (
            self._is_cache_expired(channel_id)
            or channel_id not in self.channel_commands
        ):
            logger.debug(
                f"Cache expired/missing for channel {channel_id}, auto-reloading"
            )
            # 非同步重新載入（不等待結果）
            asyncio.create_task(self.reload_channel_commands(channel_id))
            return None

        channel_commands = self.channel_commands.get(channel_id, {})
        return channel_commands.get(cmd_name)

    def _is_cache_expired(self, channel_id: str) -> bool:
        """檢查頻道快取是否過期"""
        if channel_id not in self.cache_timestamps:
            return True

        current_time = time.time()
        last_update = self.cache_timestamps[channel_id]
        return current_time - last_update > self.cache_ttl

    async def reload_channel_commands(self, channel_id: str) -> None:
        """重新載入特定頻道的指令 (當新增/修改/刪除指令時使用)"""
        try:
            async with self.bot.token_database.acquire() as connection:
                rows = await connection.fetch(
                    """SELECT command_name, response_text, cooldown_seconds, user_level, usage_count, created_at
                       FROM custom_commands 
                       WHERE channel_id = $1 AND is_active = true""",
                    channel_id,
                )

            # 重新建立該頻道的指令字典
            self.channel_commands[channel_id] = {}
            for row in rows:
                cmd_name = row["command_name"]
                self.channel_commands[channel_id][cmd_name] = dict(row)

            # 更新快取時間戳
            self.cache_timestamps[channel_id] = time.time()
            logger.info(f"Reloaded {len(rows)} commands for channel {channel_id}")

        except Exception as e:
            logger.error(f"Failed to reload channel commands: {e}")

    @commands.Component.listener()  # type: ignore[misc]
    async def event_message(self, message: Any) -> None:
        """監聽訊息並處理自訂指令"""
        # 過濾機器人訊息
        if is_self_message(self, message):
            return

        # 確保已載入指令
        if not self.loaded:
            return

        try:
            message_text = message.text.strip()
            channel_id = message.broadcaster.id

            # 從緩存中取得前綴，避免每次查詢資料庫
            prefix = self.channel_prefixes.get(channel_id, "!")

            if not message_text.startswith(prefix):
                return

            # 提取指令名稱
            cmd_parts = message_text[len(prefix) :].split()
            if not cmd_parts:
                return
            cmd_name = cmd_parts[0].lower()
            if not cmd_name:
                return

            # 從記憶體中查詢該頻道的自訂指令
            custom_cmd = self.get_channel_command(channel_id, cmd_name)

            if custom_cmd:
                # 建立輕量級 context
                context = FakeContext(self.bot, message, prefix)

                # 執行自訂指令
                # type: ignore[arg-type]
                await self.execute_custom_command(context, custom_cmd)

        except Exception as e:
            logger.error(f"Error processing custom command: {e}")

    async def check_cooldown(
        self, channel_id: str, user_id: str, cmd_name: str, cooldown_seconds: int
    ) -> bool:
        """檢查指令冷卻時間（記憶體版本）"""
        try:
            cooldown_key = (channel_id, user_id, cmd_name)
            current_time = time.time()

            # 檢查記憶體中的冷卻時間
            if cooldown_key in self.command_cooldowns:
                last_used = self.command_cooldowns[cooldown_key]
                if current_time - last_used < cooldown_seconds:
                    return False

            # 更新冷卻時間
            self.command_cooldowns[cooldown_key] = current_time

            # 定期清理過期的冷卻記錄 (每 1000 次調用清理一次)
            if len(self.command_cooldowns) % 1000 == 0:
                self._cleanup_expired_cooldowns()

            return True

        except Exception:
            return True

    def _cleanup_expired_cooldowns(self) -> None:
        """清理過期的冷卻記錄"""
        try:
            current_time = time.time()
            # 移除 1 小時前的記錄
            expired_threshold = current_time - 3600

            expired_keys = [
                key
                for key, last_used in self.command_cooldowns.items()
                if last_used < expired_threshold
            ]

            for key in expired_keys:
                del self.command_cooldowns[key]

            if expired_keys:
                logger.debug(f"Cleaned up {len(expired_keys)} expired cooldown records")

        except Exception as e:
            logger.error(f"Error cleaning up cooldowns: {e}")

    def check_user_permission(self, ctx: Any, required_level: str) -> bool:
        """檢查使用者權限"""
        if required_level == "everyone":
            return True
        elif required_level == "subscriber":
            return (
                getattr(ctx.chatter, "is_subscriber", False)
                or getattr(ctx.chatter, "is_mod", False)
                or ctx.chatter.id == self.bot.owner_id
            )
        elif required_level == "mod":
            return (
                getattr(ctx.chatter, "is_mod", False)
                or ctx.chatter.id == self.bot.owner_id
            )
        elif required_level == "owner":
            return ctx.chatter.id == self.bot.owner_id
        return False

    def process_variables(self, text: str, ctx: Any) -> str:
        """處理回應文字中的變數"""
        replacements = {
            "{user}": ctx.chatter.name or "Unknown",
            "{channel}": getattr(ctx.channel, "name", "Unknown"),
            "{time}": datetime.now().strftime("%H:%M"),
            "{date}": datetime.now().strftime("%Y-%m-%d"),
        }

        for var, value in replacements.items():
            text = text.replace(var, value)

        return text

    async def execute_custom_command(self, ctx: Any, cmd_data: dict[str, Any]) -> None:
        """執行自訂指令 - 核心執行邏輯"""
        try:
            channel_id = (
                ctx.broadcaster.id if hasattr(ctx, "broadcaster") else self.bot.owner_id
            )
            cmd_name = cmd_data["command_name"]
            cooldown = cmd_data["cooldown_seconds"]
            user_level = cmd_data["user_level"]
            response_text = cmd_data["response_text"]

            # 權限檢查
            if not self.check_user_permission(ctx, user_level):
                await ctx.reply("權限不足")
                return

            # 冷卻檢查
            if not await self.check_cooldown(
                channel_id, ctx.chatter.id, cmd_name, cooldown
            ):
                return

            # 變數處理與執行
            processed_response = self.process_variables(response_text, ctx)
            await ctx.reply(processed_response)

            # 記錄使用
            await self.bot.log_command_usage(channel_id, ctx.chatter.id, cmd_name)

        except Exception as e:
            await ctx.reply(f"指令執行失敗: {e}")

    @commands.command(name="_custom_reply", hidden=True)  # type: ignore[misc]
    async def custom_reply_dummy(self, ctx: commands.Context) -> None:
        """用於 context hack 的虛擬指令"""
        pass


async def setup(bot: Any) -> None:
    global _component_instance
    component = CustomCommands(bot)
    await bot.add_component(component)

    # 保存全局引用
    _component_instance = component

    # 啟動時載入所有頻道的自訂指令
    await component.load_all_commands()


async def teardown(bot: Any) -> None:
    global _component_instance
    _component_instance = None
