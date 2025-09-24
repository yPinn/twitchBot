import asyncio
import logging
import time
from collections import defaultdict
from typing import Any

from twitchio.ext import commands

from utils.message_utils import is_self_message

logger = logging.getLogger(__name__)


class BeFirstComponent(commands.Component):  # type: ignore[misc]
    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self.processing_lock = asyncio.Lock()

        # 按頻道獨立的遊戲狀態
        self.channel_states: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "first_found": False,
                "winner": None,
                "last_response_time": defaultdict(float),
            }
        )
        self.response_cooldown = 5

    async def _send_announcement(
        self, broadcaster_id: str, message: str, color: str = "primary"
    ) -> bool:
        """發送公告（保持原有邏輯不變）"""
        try:
            broadcaster = self.bot.create_partialuser(broadcaster_id)
            await broadcaster.send_announcement(
                moderator=self.bot.bot_id, message=message, color=color
            )
            logger.info(f"Announcement sent: {message}")
            return True
        except Exception as e:
            logger.error(f"Failed to send announcement: {e}")
            return False

    def _should_respond(self, channel_id: str, user_id: str) -> bool:
        """檢查是否應該回應該用戶（防刷）"""
        current_time = time.time()
        channel_state = self.channel_states[channel_id]
        last_time = channel_state["last_response_time"].get(user_id, 0)

        if current_time - last_time >= self.response_cooldown:
            channel_state["last_response_time"][user_id] = current_time
            return True
        return False

    def _cleanup_old_records(self, channel_id: str) -> None:
        """清理10分鐘前的記錄"""
        current_time = time.time()
        channel_state = self.channel_states[channel_id]
        last_response_time = channel_state["last_response_time"]

        expired_users = [
            user_id
            for user_id, timestamp in last_response_time.items()
            if current_time - timestamp > 600
        ]
        for user_id in expired_users:
            del last_response_time[user_id]

    async def _reply_with_context_hack(self, payload: Any, message: str) -> bool:
        """使用 context hack 實現真正回覆"""
        try:
            original_text = payload.text
            payload.text = "!_befirst_reply"
            ctx = self.bot.get_context(payload)
            payload.text = original_text

            if ctx and hasattr(ctx, "reply"):
                await ctx.reply(message)
                return True
            else:
                # 降級到普通發送
                await payload.broadcaster.send_message(
                    sender=self.bot.bot_id, message=f"@{payload.chatter.name} {message}"
                )
                return True

        except Exception as e:
            logger.error(f"Context hack failed: {e}")
            # 降級備用方案
            await payload.broadcaster.send_message(
                sender=self.bot.bot_id, message=f"@{payload.chatter.name} {message}"
            )
            return False

    @commands.Component.listener()  # type: ignore[misc]
    async def event_message(self, payload: Any) -> None:
        """監聽搶第一"""
        try:
            if is_self_message(self.bot, payload):
                return

            # 只處理 "1"
            if payload.text.strip() != "1":
                return

            async with self.processing_lock:
                current_user = payload.chatter.display_name or payload.chatter.name
                user_id = payload.chatter.id
                channel_id = payload.broadcaster.id

                # 取得頻道狀態
                channel_state = self.channel_states[channel_id]

                # 定期清理過期記錄
                self._cleanup_old_records(channel_id)

                if not channel_state["first_found"]:
                    # 第一個搶到
                    channel_state["first_found"] = True
                    channel_state["winner"] = current_user

                    announcement_text = f"🎉 恭喜 {current_user} 搶到沙發！"
                    success = await self._send_announcement(
                        channel_id, announcement_text, "primary"
                    )

                    if not success:
                        await self._reply_with_context_hack(
                            payload, f"🎉 恭喜 {current_user} 搶到沙發！"
                        )

                    logger.info(f"{current_user} got first in channel {channel_id}")

                else:
                    # 後續用戶防刷檢查
                    if not self._should_respond(channel_id, user_id):
                        return

                    winner = channel_state["winner"]
                    if current_user == winner:
                        await self._reply_with_context_hack(
                            payload, "你已經搶到沙發了，N洗皮！"
                        )
                    else:
                        await self._reply_with_context_hack(
                            payload, f"太慢了！ @{winner} 已經搶到沙發了！"
                        )

        except Exception as e:
            logger.error(f"Be-first processing error: {e}")

    def reset_game(self, channel_id: str | None = None) -> None:
        """重置遊戲狀態"""
        if channel_id:
            # 重置特定頻道
            if channel_id in self.channel_states:
                self.channel_states[channel_id] = {
                    "first_found": False,
                    "winner": None,
                    "last_response_time": defaultdict(float),
                }
                logger.info(f"Channel {channel_id} be-first game reset")
            else:
                logger.warning(f"Channel {channel_id} has no game state to reset")
        else:
            # 重置所有頻道（保持向後兼容）
            self.channel_states.clear()
            logger.info("All channels be-first game reset")

    @commands.command(name="_befirst_reply", hidden=True)  # type: ignore[misc]
    async def befirst_reply_dummy(self, ctx: commands.Context) -> None:
        """虛擬指令，用於 context hack"""
        pass

    # type: ignore[misc]
    @commands.command(name="resetfirst", aliases=["重置第一", "rf"])
    # type: ignore[misc]
    @commands.cooldown(rate=1, per=10, key=commands.BucketType.channel)
    @commands.is_elevated()  # type: ignore[misc]
    async def reset_command(self, ctx: commands.Context) -> None:
        """重置搶第一遊戲（僅管理員）"""
        try:
            channel_id = ctx.broadcaster.id
            self.reset_game(channel_id)
            announcement_text = "🔄 沙發又空下來了！"
            success = await self._send_announcement(
                channel_id, announcement_text, "blue"
            )

            if not success:
                await ctx.reply("🔄 沙發又空下來了！")

            logger.info(f"Admin {ctx.chatter.name} reset channel {channel_id} game")

        except Exception as e:
            logger.error(f"Reset command error: {e}")
            await ctx.reply("❌ 重置失敗")


async def setup(bot: Any) -> None:
    await bot.add_component(BeFirstComponent(bot))
    logger.info("Be-first component loaded")


async def teardown(bot: Any) -> None:
    logger.info("Be-first component unloaded")
