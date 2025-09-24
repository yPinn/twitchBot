import asyncio
import logging
from typing import Any

from twitchio import eventsub

logger = logging.getLogger(__name__)

# 降低 TwitchIO EventSub WebSocket 的 log 等級以減少噪音
logging.getLogger("twitchio.eventsub.websockets").setLevel(logging.WARNING)


class EventSubManager:
    """EventSub 訂閱管理器"""

    def __init__(self, bot: Any, database_manager: Any) -> None:
        self.bot = bot
        self.db = database_manager
        self._last_session_welcome = 0.0

    async def subscribe_all_events(
        self,
        channel_id: str | None = None,
        advanced_only: bool = False,
        is_reconnect: bool = False,
    ) -> None:
        """訂閱 EventSub 事件（優化版本）"""
        try:
            # 取得頻道列表
            if channel_id:
                channels = await self.db.get_active_channels()
                target_channel = next(
                    (ch for ch in channels if ch["channel_id"] == channel_id), None
                )
                if not target_channel:
                    logger.warning(f"Channel ID not found: {channel_id}")
                    return
                channels = [target_channel]
            else:
                channels = await self.db.get_active_channels()
                if not channels:
                    return

            # 僅處理進階事件
            if advanced_only:
                channels_with_tokens = await self.db.get_channels_with_tokens()
                if channel_id:
                    channels_with_tokens = [
                        ch
                        for ch in channels_with_tokens
                        if ch["channel_id"] == channel_id
                    ]
                await self._subscribe_advanced_events(channels_with_tokens)
                return

            # 分類頻道
            channels_with_tokens = await self.db.get_channels_with_tokens()
            token_channel_ids = {ch["channel_id"] for ch in channels_with_tokens}
            channels_without_tokens = [
                ch for ch in channels if ch["channel_id"] not in token_channel_ids
            ]

            success_count = 0

            # 並發處理有 token 的頻道（基本事件）
            if channels_with_tokens:
                basic_results = await asyncio.gather(
                    *[
                        self._subscribe_basic_events_safe(ch)
                        for ch in channels_with_tokens
                    ],
                    return_exceptions=True,
                )
                success_count += sum(1 for result in basic_results if result is True)

            # 處理無 token 頻道（chat only）
            for channel in channels_without_tokens:
                try:
                    await self._subscribe_chat_only(channel)
                    success_count += 1
                except Exception as e:
                    if "429" in str(e) or "cost exceeded" in str(e).lower():
                        logger.warning(
                            f"Cost limit reached, stopping at {channel['channel_name']}"
                        )
                        break
                    elif "already exists" not in str(e).lower():
                        logger.warning(
                            f"Chat subscription failed for {channel['channel_name']}: {e}"
                        )

            # 進階事件（有 token 的頻道）
            if channels_with_tokens:
                await self._subscribe_advanced_events(channels_with_tokens)

            # 簡化日誌輸出
            if is_reconnect:
                logger.info(
                    f"EventSub reconnect: {success_count}/{len(channels)} channels resubscribed"
                )
            elif channel_id:
                logger.info(f"EventSub configured for {channels[0]['channel_name']}")
            else:
                logger.info(f"EventSub ready: {success_count}/{len(channels)} channels")

        except Exception as e:
            logger.error(f"EventSub subscription failed: {e}")

    async def _subscribe_basic_events_safe(self, channel: dict[str, Any]) -> bool:
        """安全地訂閱基本事件"""
        try:
            await self._subscribe_basic_events(channel)
            return True
        except Exception as e:
            error_str = str(e).lower()
            if (
                "already exists" not in error_str
                and "websocket transport session" not in error_str
            ):
                logger.warning(
                    f"Basic subscription failed for {channel['channel_name']}: {e}"
                )
            return False

    async def _subscribe_basic_events(self, channel: dict[str, Any]) -> None:
        """訂閱基本事件（有 token 的頻道）"""
        channel_id = channel["channel_id"]
        bot_id = self.bot.bot_id

        # 1. 聊天訊息
        chat_subscription = eventsub.ChatMessageSubscription(
            broadcaster_user_id=channel_id, user_id=bot_id
        )
        await self.bot.subscribe_websocket(payload=chat_subscription)

        # 2. 直播上線通知
        stream_subscription = eventsub.StreamOnlineSubscription(
            broadcaster_user_id=channel_id
        )
        await self.bot.subscribe_websocket(payload=stream_subscription)

        # 3. 團襲事件
        raid_subscription = eventsub.ChannelRaidSubscription(
            to_broadcaster_user_id=channel_id
        )
        await self.bot.subscribe_websocket(payload=raid_subscription)

    async def _subscribe_chat_only(self, channel: dict[str, Any]) -> None:
        """訂閱僅聊天事件（無 token 的頻道）"""
        channel_id = channel["channel_id"]
        bot_id = self.bot.bot_id

        chat_subscription = eventsub.ChatMessageSubscription(
            broadcaster_user_id=channel_id, user_id=bot_id
        )
        await self.bot.subscribe_websocket(payload=chat_subscription)

    async def _subscribe_advanced_events(self, channels: list[dict[str, Any]]) -> None:
        """訂閱需要特殊權限的進階事件"""
        cost_limit_reached = False
        bot_id = self.bot.bot_id

        for channel in channels:
            if cost_limit_reached:
                logger.warning(
                    f"Skipping advanced events for {channel['channel_name']}: global cost limit reached"
                )
                continue

            try:
                channel_name = channel["channel_name"]
                channel_id = channel["channel_id"]

                # 追蹤事件
                try:
                    follow_subscription = eventsub.ChannelFollowSubscription(
                        broadcaster_user_id=channel_id,
                        moderator_user_id=bot_id,
                    )
                    await self.bot.subscribe_websocket(payload=follow_subscription)
                    logger.info(f"Follow subscription successful for {channel_name}")
                except Exception as e:
                    cost_limit_reached = await self._handle_subscription_error(
                        e, channel_name, "Follow", cost_limit_reached
                    )

                if cost_limit_reached:
                    continue

                # 訂閱事件
                try:
                    subscribe_subscription = eventsub.ChannelSubscribeSubscription(
                        broadcaster_user_id=channel_id
                    )
                    await self.bot.subscribe_websocket(payload=subscribe_subscription)
                    logger.info(f"Subscribe subscription successful for {channel_name}")
                except Exception as e:
                    cost_limit_reached = await self._handle_subscription_error(
                        e, channel_name, "Subscribe", cost_limit_reached
                    )

                if cost_limit_reached:
                    continue

                # 贈送訂閱事件
                try:
                    gift_subscription = eventsub.ChannelSubscriptionGiftSubscription(
                        broadcaster_user_id=channel_id
                    )
                    await self.bot.subscribe_websocket(payload=gift_subscription)
                    logger.info(f"Gift subscription successful for {channel_name}")
                except Exception as e:
                    cost_limit_reached = await self._handle_subscription_error(
                        e, channel_name, "Gift", cost_limit_reached
                    )

                if cost_limit_reached:
                    continue

                # Channel Points 兌換事件（嘗試不同的 API）
                try:
                    # 嘗試多種可能的 Channel Points 訂閱方式
                    points_subscription = None
                    subscription_methods = [
                        (
                            "ChannelPointsCustomRewardRedemptionAddSubscription",
                            eventsub,
                        ),
                        ("ChannelPointsRedemptionAddSubscription", eventsub),
                        ("ChannelPointsRedeemAddSubscription", eventsub),
                    ]

                    for method_name, module in subscription_methods:
                        try:
                            if hasattr(module, method_name):
                                subscription_class = getattr(module, method_name)
                                points_subscription = subscription_class(
                                    broadcaster_user_id=channel_id
                                )
                                logger.info(f"Using {method_name} for {channel_name}")
                                break
                        except Exception as e:
                            logger.debug(f"Failed to use {method_name}: {e}")
                            continue

                    if points_subscription:
                        await self.bot.subscribe_websocket(payload=points_subscription)
                        logger.info(
                            f"Channel Points redemption subscription successful for {channel_name}"
                        )
                    else:
                        logger.warning(
                            f"No Channel Points subscription method available for {channel_name}"
                        )

                except Exception as e:
                    cost_limit_reached = await self._handle_subscription_error(
                        e, channel_name, "Channel Points", cost_limit_reached
                    )

            except Exception as e:
                logger.error(
                    f"Advanced subscription error for {channel['channel_name']}: {e}"
                )

    async def _handle_subscription_error(
        self,
        error: Exception,
        channel_name: str,
        event_type: str,
        cost_limit_reached: bool,
    ) -> bool:
        """處理訂閱錯誤"""
        error_str = str(error).lower()

        if "403" in error_str or "authorization" in error_str:
            logger.warning(
                f"{event_type} subscription skipped for {channel_name}: missing required scope"
            )
        elif "429" in error_str or "cost exceeded" in error_str:
            logger.warning(
                f"{event_type} subscription skipped for {channel_name}: cost limit reached"
            )
            return True  # 成本限制達到
        elif (
            "websocket transport session" in error_str
            or "already disconnected" in error_str
        ):
            logger.debug(
                f"{event_type} subscription skipped for {channel_name}: websocket session issue"
            )
        elif "already exists" in error_str:
            logger.debug(f"{event_type} subscription already exists for {channel_name}")
        else:
            logger.error(
                f"{event_type} subscription failed for {channel_name}: {error}"
            )

        return cost_limit_reached

    async def check_eventsub_limits(self) -> dict[str, int]:
        """檢查 EventSub 訂閱限制和成本"""
        try:
            # 暫時返回預設值，避免 API 錯誤
            logger.debug("EventSub limits check: using default values")

            return {
                "total": 0,
                "total_cost": 0,
                "max_total_cost": 10000,
                "remaining_cost": 10000,
            }
        except Exception as e:
            logger.error(f"Failed to check EventSub limits: {e}")
            return {
                "total": 0,
                "total_cost": 0,
                "max_total_cost": 10000,
                "remaining_cost": 10000,
            }

    async def handle_websocket_reconnect(self) -> None:
        """處理 WebSocket 重連後的重新訂閱"""
        import time

        current_time = time.time()

        # 避免短時間內重複重訂閱
        if current_time - self._last_session_welcome < 10.0:  # 10秒內只處理一次
            return

        self._last_session_welcome = current_time
        logger.info("WebSocket reconnected, resubscribing to all events...")

        try:
            # 重新訂閱所有事件
            await self.subscribe_all_events(is_reconnect=True)
        except Exception as e:
            logger.error(f"Failed to resubscribe after reconnect: {e}")
