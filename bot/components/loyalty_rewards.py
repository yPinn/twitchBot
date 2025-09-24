import logging
import re
from typing import Any

from twitchio.ext import commands

logger = logging.getLogger(__name__)


class LoyaltyRewards(commands.Component):  # type: ignore[misc]

    REWARD_HANDLERS = {
        "+ Niibot": "_handle_add_channel",
    }

    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self.bot.register_message_handler(self.handle_loyalty_message)
        super().__init__()

    async def handle_loyalty_message(self, message: Any) -> None:
        """處理聊天室兌換訊息"""
        try:
            if not message.text:
                return

            content = message.text.strip()
            reward_match = re.search(r"已兌換「(.+?)」", content)
            if not reward_match or not self._is_owner_channel(message):
                return

            reward_name = reward_match.group(1).strip()
            handler_name = self.REWARD_HANDLERS.get(reward_name)

            if handler_name and hasattr(self, handler_name):
                logger.info(f"Chat reward: {reward_name}")
                await getattr(self, handler_name)(message, content)

        except Exception as e:
            logger.error(f"Loyalty message error: {e}")

    def _is_owner_channel(self, message: Any) -> bool:
        """檢查是否在 owner 頻道"""
        try:
            # TwitchIO 3.x: 使用 message.broadcaster.id
            return (
                message.broadcaster.id == self.bot.owner_id
                if hasattr(message, "broadcaster")
                else False
            )
        except Exception:
            return False

    async def _handle_add_channel(self, message: Any, content: str) -> None:
        """處理 + Niibot 兌換加頻道"""
        try:
            # 只在 owner 頻道中處理
            if not self._is_owner_channel(message):
                return

            logger.info(f"Processing + Niibot reward content:\n{content}")

            lines = content.split("\n")
            logger.info(f"Content split into {len(lines)} lines: {lines}")

            if len(lines) < 3:
                logger.warning(
                    f"+ Niibot reward format error: expected 3+ lines, got {len(lines)}"
                )
                return

            # 解析價格
            price_match = re.match(r"(\d+)", lines[1].strip())
            if not price_match:
                logger.warning(
                    f"+ Niibot reward: could not parse price from '{lines[1]}'"
                )
                return
            price = int(price_match.group(1))
            logger.info(f"Parsed price: {price}")

            # 解析第3行，提取兌換者和目標頻道
            user_info_line = lines[2].strip()
            logger.info(f"User info line: {user_info_line}")

            # 新格式: 轉播訂閱第 1 個月《馬拉松》發表會參與者皮先森ツ (llazypilot): 31xuy
            # 提取括號中的兌換者和冒號後的目標頻道
            user_match = re.search(r"\(([^)]+)\):", user_info_line)
            if user_match:
                requester = user_match.group(1).strip()
                channel_name = user_info_line.split(":", 1)[1].strip()
                logger.info(
                    f"Parsed requester: {requester}, target channel: {channel_name}"
                )
            else:
                # 舊格式或其他格式
                if ":" not in user_info_line:
                    logger.warning("+ Niibot reward: no ':' found in user info line")
                    return
                parts = user_info_line.split(":", 1)
                requester = parts[0].strip()
                channel_name = parts[1].strip()
                logger.info(
                    f"Fallback parse - requester: {requester}, target channel: {channel_name}"
                )

            await self._execute_add_channel(message, channel_name, requester, price)

        except Exception as e:
            logger.error(f"Add channel reward error: {e}")

    async def _execute_add_channel(
        self, message: Any, channel_name: str, requester: str, price: int
    ) -> None:
        """執行加頻道操作"""
        success = False
        error_message = None

        try:
            users = await self.bot.fetch_users(logins=[channel_name])
            if not users:
                error_message = f"找不到頻道：{channel_name}"
                await self._send_reward_response(message, f"❌ {error_message}")
                return

            target_user = users[0]
            channel_id = target_user.id
            actual_channel_name = target_user.name

            # 檢查是否已存在
            existing_channels = await self.bot.get_active_channels()
            if any(ch["channel_id"] == channel_id for ch in existing_channels):
                error_message = f"頻道 {actual_channel_name} 已在監聽清單中"
                await self._send_reward_response(message, f"ℹ️ {error_message}")
                return

            # 新增頻道 (基本權限)
            success = await self.bot.add_channel(
                channel_id, actual_channel_name, f"loyalty_reward:{requester}"
            )

            if success:
                # 訂閱基本 chat EventSub
                try:
                    await self._subscribe_chat_only_for_new_channel(channel_id)
                except Exception as e:
                    logger.warning(f"EventSub failed for {actual_channel_name}: {e}")

                # 分兩個消息發送避免過長
                await self._send_reward_response(
                    message,
                    f"✅ 已加入頻道：{actual_channel_name} - 感謝 {requester} 的兌換！",
                )
                await self._send_reward_response(
                    message, f"請前往該頻道給予 Bot 版主權限：/mod {self.bot.user.name}"
                )
            else:
                error_message = f"加入頻道失敗：{actual_channel_name}"
                await self._send_reward_response(message, f"❌ {error_message}")

        except Exception as e:
            error_message = str(e)
            logger.error(f"Add channel failed: {e}")
            await self._send_reward_response(message, "❌ 處理失敗")

        finally:
            # 記錄兌換歷史
            await self._log_niibot_redemption(
                self.bot.owner_id,
                requester,
                channel_name,
                price,
                success,
                error_message,
            )

    # 移除不使用的泛型處理器

    async def _subscribe_chat_only_for_new_channel(self, channel_id: str) -> None:
        """為新頻道訂閱聊天事件"""
        try:
            from twitchio import eventsub

            chat_subscription = eventsub.ChatMessageSubscription(
                broadcaster_user_id=channel_id, user_id=self.bot.bot_id
            )
            logger.info(f"Attempting EventSub for channel {channel_id}")
            await self.bot.subscribe_websocket(payload=chat_subscription)
            logger.info(f"✅ EventSub subscription successful for channel {channel_id}")
        except Exception as e:
            # 處理重複訂閱錯誤 - 這是正常情況
            if "already exists" not in str(e).lower():
                logger.warning(f"Chat EventSub failed for channel {channel_id}: {e}")
                raise  # 重新拋出錯誤讓上層處理
            else:
                logger.debug(
                    f"Chat subscription already exists for channel {channel_id}"
                )

    async def _send_reward_response(self, message: Any, response: str) -> None:
        """發送獎勵處理回應訊息"""
        try:
            await message.respond(response)
        except Exception as e:
            logger.error(f"Failed to send reward response: {e}")

    @commands.Component.listener()  # type: ignore[misc]
    async def event_custom_redemption_add(self, payload: Any) -> None:
        """處理 Channel Points 兌換事件"""
        try:
            channel_id = payload.broadcaster.id
            reward_title = payload.reward.title
            user_name = payload.user.display_name
            user_input = payload.user_input

            logger.info(
                f"Channel Points: {user_name} -> {reward_title}, input: {user_input}"
            )

            # 檢查處理器和權限
            handler_name = self.REWARD_HANDLERS.get(reward_title)
            if not handler_name or channel_id != self.bot.owner_id:
                return

            logger.info(f"Processing {reward_title} from {user_name}: {user_input}")

            # 調用處理器
            eventsub_handler_name = f"{handler_name}_from_eventsub"
            if hasattr(self, eventsub_handler_name):
                await getattr(self, eventsub_handler_name)(payload)

        except Exception as e:
            logger.error(f"Failed to handle channel points redemption: {e}")

    async def _handle_add_channel_from_eventsub(self, payload: Any) -> None:
        """處理 EventSub 的 + Niibot 兌換"""
        success = False
        error_message = None
        requester = payload.user.display_name
        cost = payload.reward.cost
        channel_name = payload.user_input.strip() if payload.user_input else ""

        try:
            if not channel_name:
                error_message = "缺少頻道名稱"
                return

            users = await self.bot.fetch_users(logins=[channel_name])
            if not users:
                error_message = f"找不到頻道: {channel_name}"
                logger.warning(f"Channel not found: {channel_name}")
                await self._send_redemption_response(f"❌ 找不到頻道：{channel_name}")
                return

            target_user = users[0]

            # 檢查是否已存在
            existing_channels = await self.bot.get_active_channels()
            if any(ch["channel_id"] == target_user.id for ch in existing_channels):
                await self._send_redemption_response(
                    f"ℹ️ 頻道 {target_user.name} 已在監聽清單中"
                )
                return

            success = await self.bot.add_channel(
                target_user.id, target_user.name, f"eventsub_reward:{requester}"
            )

            if success:
                try:
                    await self._subscribe_chat_only_for_new_channel(target_user.id)
                except Exception as e:
                    logger.warning(f"EventSub failed for {target_user.name}: {e}")
                logger.info(f"✅ Added channel: {target_user.name} (by {requester})")
                await self._send_redemption_response(
                    f"✅ 已成功加入頻道：{target_user.name}。請前往該頻道給予 Bot 版主權限以啟用完整功能：/mod {self.bot.user.name}"
                )
            else:
                error_message = f"加入頻道失敗: {target_user.name}"
                await self._send_redemption_response(
                    f"❌ 加入頻道失敗：{target_user.name}"
                )

        except Exception as e:
            error_message = str(e)
            logger.error(f"Add channel failed: {e}")

        finally:
            await self._log_niibot_redemption(
                self.bot.owner_id, requester, channel_name, cost, success, error_message
            )

    async def _log_niibot_redemption(
        self,
        channel_id: str,
        requester: str,
        target_channel: str,
        cost: int,
        success: bool,
        error_message: str | None,
    ) -> None:
        """記錄兌換歷史"""
        try:
            async with self.bot.token_database.acquire() as connection:
                await connection.execute(
                    """INSERT INTO niibot_redemptions 
                       (channel_id, requester_name, target_channel, cost, success, error_message)
                       VALUES ($1, $2, $3, $4, $5, $6)""",
                    channel_id,
                    requester,
                    target_channel,
                    cost,
                    success,
                    error_message,
                )
        except Exception as e:
            logger.error(f"Failed to log redemption: {e}")

    async def _send_redemption_response(self, message: str) -> None:
        """發送兌換結果回應到 owner 頻道"""
        try:
            channels = await self.bot.get_active_channels()
            owner_channel = next(
                (ch for ch in channels if ch["channel_id"] == self.bot.owner_id), None
            )

            if owner_channel:
                # TwitchIO 3.x: 使用 PartialUser.send_message 方法
                user = self.bot.create_partialuser(
                    owner_channel["channel_id"], owner_channel["channel_name"]
                )
                await user.send_message(sender=self.bot.user, message=message)
        except Exception as e:
            logger.error(f"Failed to send redemption response: {e}")

    async def _send_channel_message(self, channel_id: str, message: str) -> None:
        """發送訊息到指定頻道"""
        try:
            channels = await self.bot.get_active_channels()
            target_channel = next(
                (ch for ch in channels if ch["channel_id"] == channel_id), None
            )

            if not target_channel:
                logger.warning(f"Channel not found: {channel_id}")
                return

            # TwitchIO 3.x: 使用 PartialUser.send_message 方法
            user = self.bot.create_partialuser(
                target_channel["channel_id"], target_channel["channel_name"]
            )
            await user.send_message(sender=self.bot.user, message=message)

        except Exception as e:
            logger.error(f"Failed to send channel message: {e}")


async def setup(bot: Any) -> None:
    component = LoyaltyRewards(bot)
    await bot.add_component(component)
