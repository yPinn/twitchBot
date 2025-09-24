import logging
from typing import Any

import twitchio
from twitchio.ext import commands

logger = logging.getLogger(__name__)


class EventHandlers(commands.Component):  # type: ignore[misc]
    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self.TIER_MAPPING = {"1000": "Tier 1", "2000": "Tier 2", "3000": "Tier 3"}
        super().__init__()

    async def _send_bot_message(self, broadcaster: Any, message: str) -> None:
        try:
            await broadcaster.send_message(
                message, sender=self.bot.create_partialuser(self.bot.bot_id)
            )
        except Exception as e:
            logger.error(f"Send message failed: {e}")
            raise

    @commands.Component.listener()  # type: ignore[misc]
    async def event_stream_online(self, payload: twitchio.StreamOnline) -> None:
        try:
            logger.info(f"Stream started: {payload.broadcaster.name}")
        except Exception as e:
            logger.error(f"Stream start event failed: {e}")

    @commands.Component.listener()  # type: ignore[misc]
    async def event_channel_raid(self, payload: twitchio.ChannelRaid) -> None:
        try:
            raider = payload.from_broadcaster
            broadcaster = payload.to_broadcaster
            viewer_count = payload.viewer_count

            await self._send_bot_message(
                broadcaster,
                f"感謝 @{raider.display_name} 帶著 {viewer_count} 位觀眾降落 BloodTrail",
            )

            try:
                await broadcaster.send_shoutout(
                    to_broadcaster=raider.id, moderator=broadcaster.id
                )
            except Exception:
                await self._send_bot_message(
                    broadcaster,
                    f"好台推薦： {raider.display_name} | twitch.tv/{raider.name}",
                )

        except Exception as e:
            logger.error(f"Raid event handling failed: {e}")

    @commands.Component.listener()  # type: ignore[misc]
    async def event_channel_follow(self, payload: twitchio.ChannelFollow) -> None:
        try:
            follower = payload.user
            broadcaster = payload.broadcaster

            await self._send_bot_message(
                broadcaster, f"感謝 {follower.display_name} 的追隨!! BloodTrail"
            )

        except Exception as e:
            logger.error(f"Follow event handling failed: {e}")

    @commands.Component.listener()  # type: ignore[misc]
    async def event_channel_subscribe(self, payload: twitchio.ChannelSubscribe) -> None:
        try:
            subscriber = payload.user
            broadcaster = payload.broadcaster
            tier_text = self.TIER_MAPPING.get(payload.tier, "Unknown Tier")

            await self._send_bot_message(
                broadcaster,
                f"感謝 {subscriber.display_name} 的 {tier_text} 訂閱！非常感謝你的支持！ BloodTrail",
            )

        except Exception as e:
            logger.error(f"Subscription event handling failed: {e}")

    @commands.Component.listener()  # type: ignore[misc]
    async def event_channel_subscription_gift(
        self, payload: twitchio.ChannelSubscriptionGift
    ) -> None:
        try:
            gifter = payload.user
            broadcaster = payload.broadcaster
            total = payload.total
            tier_text = self.TIER_MAPPING.get(payload.tier, "Unknown Tier")

            if payload.anonymous:
                msg = f"感謝匿名觀眾贈送了 {total} 個 {tier_text} 訂閱！ BloodTrail"
            elif gifter:
                msg = f"感謝 {gifter.display_name} 贈送了 {total} 個 {tier_text} 訂閱！ BloodTrail"
            else:
                msg = (
                    f"感謝觀眾贈送了 {total} 個 {tier_text} 訂閱！非常慷慨！ BloodTrail"
                )

            await self._send_bot_message(broadcaster, msg)

        except Exception as e:
            logger.error(f"Gift subscription event handling failed: {e}")

    @commands.command()  # type: ignore[misc]
    async def list_commands(self, ctx: commands.Context) -> None:
        try:
            cmds = list(self.bot.commands.keys())
            await ctx.send(f"Bot 總指令數: {len(cmds)}")
            if cmds:
                await ctx.send(f"部分指令: {', '.join(cmds[:10])}")
        except Exception as e:
            await ctx.send(f"❌ 列出指令失敗: {e}")

    @commands.command()  # type: ignore[misc]
    @commands.is_broadcaster()  # type: ignore[misc]
    async def check_permissions(self, ctx: commands.Context) -> None:
        results = []
        try:
            await ctx.broadcaster.fetch_chat_settings()
            results.append("聊天設定: ✅")
        except Exception as e:
            results.append(f"聊天設定: ❌ ({str(e)[:30]})")

        results.append("發送訊息: ✅")
        for r in results:
            await ctx.send(r)


async def setup(bot: Any) -> None:
    component = EventHandlers(bot)
    await bot.add_component(component)
    logger.info("EventHandlers loaded")


async def teardown(bot: Any) -> None:
    logger.info("EventHandlers unloaded")
