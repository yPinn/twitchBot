import logging
from typing import TYPE_CHECKING

import twitchio
from twitchio.ext import commands

from utils.message_utils import is_self_message

if TYPE_CHECKING:
    # 避免循環導入，在類型檢查時才導入
    pass

logger = logging.getLogger(__name__)


class BaseComponent(commands.Component):
    """
    基礎 Component 範例

    TwitchIO 3.x Component 的標準寫法：
    - 繼承 commands.Component
    - __init__ 接收 bot 參數
    - 可以包含命令、事件監聽器等
    """

    def __init__(self, bot: commands.Bot) -> None:
        """
        初始化 Component

        Args:
            bot: Bot 實例，通常是 commands.Bot 或 commands.AutoBot
        """
        self.bot = bot
        logger.info(f"BaseComponent initialized for bot: {bot.bot_id}")

    # ==================== 命令範例 ====================

    @commands.command(name="hello")
    async def hello_command(self, ctx: commands.Context) -> None:
        """
        基本的問候命令
        用法: !hello
        """
        await ctx.send(f"Hello {ctx.chatter.display_name}! 👋")

    @commands.command(name="info")
    async def info_command(self, ctx: commands.Context) -> None:
        """
        顯示頻道資訊
        用法: !info
        """
        channel = ctx.channel
        chatter = ctx.chatter

        message = f"頻道: {channel.name} | 用戶: {chatter.display_name}"
        await ctx.send(message)

    @commands.command(name="echo", aliases=["repeat"])
    async def echo_command(self, ctx: commands.Context, *, message: str) -> None:
        """
        重複用戶的訊息
        用法: !echo <訊息>
        別名: !repeat
        """
        await ctx.send(f"📢 {ctx.chatter.display_name} 說: {message}")

    @commands.command(name="uptime")
    async def uptime_command(self, ctx: commands.Context) -> None:
        """
        顯示直播時間 (需要 API 權限)
        用法: !uptime
        """
        try:
            # 這裡可以調用 Twitch API 獲取直播狀態
            # 由於需要適當的權限，這裡只是示範
            await ctx.send("⏰ 直播時間查詢功能需要額外的 API 權限")
        except Exception as e:
            logger.error(f"Error in uptime command: {e}")
            await ctx.send("❌ 無法獲取直播時間")

    # ==================== 事件監聽器範例 ====================

    @commands.Component.listener()  # type: ignore[misc]
    async def event_message(self, message: twitchio.ChatMessage) -> None:
        """
        聊天訊息事件監聽器

        注意: 這會監聽所有聊天訊息，請謹慎使用
        """
        if is_self_message(self, message):
            return

        # 記錄特殊訊息 (例如包含特定關鍵字)
        content = message.text.lower()
        if any(keyword in content for keyword in ["hello", "hi", "你好"]):
            logger.info(
                f"Greeting detected from {message.chatter.display_name}: {message.text}"
            )

    @commands.Component.listener()  # type: ignore[misc]
    async def event_ready(self) -> None:
        """
        Bot 準備完成事件
        """
        logger.info(f"BaseComponent ready for bot: {self.bot.bot_id}")

    # ==================== 檢查和冷卻範例 ====================

    @commands.command(name="mod_only")
    # 移除 @commands.check，改為函數內檢查
    async def mod_only_command(self, ctx: commands.Context) -> None:
        """
        僅限管理員的命令
        用法: !mod_only
        """
        if not (
            getattr(ctx.chatter, "is_mod", False)
            or getattr(ctx.chatter, "is_broadcaster", False)
        ):
            await ctx.send("⛔ 權限不足 - 僅限管理員使用")
            return
        await ctx.send("🛡️ 這是管理員專用命令！")

    @commands.command(name="broadcaster_only")
    # 移除 @commands.check，改為函數內檢查
    async def broadcaster_only_command(self, ctx: commands.Context) -> None:
        """
        僅限主播的命令
        用法: !broadcaster_only
        """
        if not getattr(ctx.chatter, "is_broadcaster", False):
            await ctx.send("⛔ 權限不足 - 僅限主播使用")
            return
        await ctx.send("👑 這是主播專用命令！")

    @commands.command(name="cooldown_test")
    @commands.cooldown(rate=1, per=30.0)  # type: ignore[misc]
    async def cooldown_command(self, ctx: commands.Context) -> None:
        """
        帶冷卻時間的命令 (每用戶 30 秒一次)
        用法: !cooldown_test
        """
        await ctx.send(f"⏱️ {ctx.chatter.display_name} 使用了冷卻命令！")

    # ==================== 群組命令範例 ====================

    @commands.group(name="admin", invoke_without_command=True)
    # 移除 @commands.check，改為函數內檢查
    async def admin_group(self, ctx: commands.Context) -> None:
        """
        管理員命令群組
        用法: !admin
        """
        if not (
            getattr(ctx.chatter, "is_broadcaster", False)
            or getattr(ctx.chatter, "is_mod", False)
        ):
            await ctx.send("⛔ 權限不足 - 僅限管理員使用")
            return
        await ctx.send("🔧 管理員命令群組 | 子命令: status, reload")

    @admin_group.command(name="status")
    async def admin_status(self, ctx: commands.Context) -> None:
        """
        顯示 Bot 狀態
        用法: !admin status
        """
        bot_status = (
            "🟢 線上"
            if hasattr(self.bot, "is_ready") and self.bot.is_ready
            else "🟢 運行中"
        )
        await ctx.send(f"Bot 狀態: {bot_status}")

    @admin_group.command(name="reload")
    async def admin_reload(self, ctx: commands.Context) -> None:
        """
        重新載入設定 (示範)
        用法: !admin reload
        """
        try:
            # 這裡可以重新載入設定檔案或重新初始化某些功能
            logger.info("Reload command executed")
            await ctx.send("🔄 設定已重新載入")
        except Exception as e:
            logger.error(f"Error in reload: {e}")
            await ctx.send("❌ 重新載入失敗")

    # ==================== 錯誤處理 ====================

    @echo_command.error
    async def echo_error(self, ctx: commands.Context, error: Exception) -> None:
        """
        echo 命令的錯誤處理
        """
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("❌ 請提供要重複的訊息！用法: !echo <訊息>")
        else:
            logger.error(f"Error in echo command: {error}")
            await ctx.send("❌ 命令執行時發生錯誤")

    @cooldown_command.error
    async def cooldown_error(self, ctx: commands.Context, error: Exception) -> None:
        """
        冷卻命令的錯誤處理
        """
        if isinstance(error, commands.CommandOnCooldown):
            retry_after = getattr(error, "retry_after", 30)
            await ctx.send(f"⏱️ 命令冷卻中，請等待 {retry_after:.1f} 秒")
        else:
            logger.error(f"Error in cooldown command: {error}")

    # ==================== 輔助方法 ====================

    def is_privileged_user(self, chatter: twitchio.Chatter) -> bool:
        """
        檢查用戶是否有特權 (主播或管理員)
        """
        return getattr(chatter, "is_broadcaster", False) or getattr(
            chatter, "is_mod", False
        )

    async def send_safe(self, ctx: commands.Context, message: str) -> None:
        """
        安全發送訊息 (帶錯誤處理)
        """
        try:
            await ctx.send(message)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")


# ==================== Component 載入/卸載函數 ====================


async def setup(bot: commands.Bot) -> None:
    """
    Component 載入函數

    這個函數會在載入 Component 時被調用
    """
    try:
        component = BaseComponent(bot)
        await bot.add_component(component)
        logger.info("BaseComponent loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load BaseComponent: {e}")
        raise


async def teardown(bot: commands.Bot) -> None:
    """
    Component 卸載函數

    這個函數會在卸載 Component 時被調用
    """
    try:
        # 在這裡可以進行清理工作
        # 例如: 關閉檔案、清理快取、停止背景任務等
        logger.info("BaseComponent teardown completed")
    except Exception as e:
        logger.error(f"Error during BaseComponent teardown: {e}")
