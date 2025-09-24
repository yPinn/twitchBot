import logging
from typing import Any

logger = logging.getLogger(__name__)


class OAuthManager:
    """OAuth 認證管理器"""

    def __init__(self, client_id: str, port: int) -> None:
        self.client_id = client_id
        self.port = port

    def generate_oauth_url_for_channel(self, channel_name: str) -> str:
        """為特定頻道生成 OAuth 授權 URL"""
        redirect_base = f"http://localhost:{self.port}"

        # 頻道專用 scope（新頻道基本權限）
        channel_scopes = [
            "user:read:chat",
            "user:write:chat",
            "channel:bot",
            "channel:read:subscriptions",  # 訂閱事件
            "moderator:read:followers",  # 追蹤事件
            "channel:read:redemptions",  # Channel Points 兌換事件
        ]

        oauth_url = (
            f"https://id.twitch.tv/oauth2/authorize"
            f"?client_id={self.client_id}"
            f"&redirect_uri={redirect_base}/oauth"
            f"&response_type=code"
            f"&scope={'+'.join(channel_scopes)}"
            f"&state=channel_{channel_name}"
        )

        return oauth_url

    async def send_oauth_invite_whisper(self, bot: Any, channel_name: str) -> bool:
        """發送 OAuth 邀請 whisper"""
        try:
            # 生成 OAuth URL
            oauth_url = self.generate_oauth_url_for_channel(channel_name)

            # 構建 whisper 訊息
            message = (
                f"🤖 嗨 {channel_name}！為了讓 Niibot 在你的頻道提供完整功能 "
                f"(如追蹤通知、訂閱事件等)，需要你的授權。"
                f"\n\n請點擊此連結完成授權：{oauth_url}"
                f"\n\n授權後 Niibot 就能在你的頻道正常運作所有進階功能了！"
            )

            # 取得該用戶資訊
            users = await bot.fetch_users(logins=[channel_name])
            if not users:
                logger.error(f"Cannot find user: {channel_name}")
                return False

            target_user = users[0]

            # 發送 whisper (需要 user:manage:whispers scope)
            try:
                # 方法1：使用 TwitchIO 3.x create_whisper
                if hasattr(bot, "create_whisper"):
                    await bot.create_whisper(
                        from_user_id=bot.bot_id,
                        to_user_id=target_user.id,
                        message=message,
                    )
                    logger.info(f"OAuth invite whisper sent to {channel_name}")
                    return True

                # 方法2：使用 HTTP API 直接發送
                else:
                    import os

                    import aiohttp

                    # 取得 bot 的存取令牌
                    async with bot.token_database.acquire() as connection:
                        token_row = await connection.fetchrow(
                            "SELECT token FROM tokens WHERE user_id = $1 LIMIT 1",
                            bot.bot_id,
                        )

                    if not token_row:
                        logger.error("找不到 bot 的 access token")
                        return False

                    access_token = token_row["token"]
                    client_id = os.getenv("CLIENT_ID")

                    # 使用 Twitch API 發送 whisper
                    headers = {
                        "Authorization": f"Bearer {access_token}",
                        "Client-Id": client_id,
                        "Content-Type": "application/json",
                    }

                    data = {"message": message}

                    url = f"https://api.twitch.tv/helix/whispers?from_user_id={bot.bot_id}&to_user_id={target_user.id}"

                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            url, headers=headers, json=data
                        ) as response:
                            if response.status == 204:
                                logger.info(
                                    f"OAuth invite whisper sent to {channel_name} via HTTP API"
                                )
                                return True
                            else:
                                error_text = await response.text()

                                # 特殊錯誤處理
                                if response.status == 401:
                                    if "verified phone number" in error_text:
                                        logger.error(
                                            f"❌ Bot 帳號需要驗證手機號碼才能發送 OAuth whisper 給 {channel_name}"
                                        )
                                    else:
                                        logger.error(
                                            f"❌ OAuth whisper 權限不足: {error_text}"
                                        )
                                elif response.status == 400:
                                    logger.error(
                                        f"❌ OAuth whisper 請求錯誤或 {channel_name} 不允許 whisper: {error_text}"
                                    )
                                elif response.status == 403:
                                    logger.error(
                                        f"❌ Bot 被 {channel_name} 封鎖或無權限發送 whisper: {error_text}"
                                    )
                                else:
                                    logger.error(
                                        f"HTTP API OAuth whisper failed ({response.status}): {error_text}"
                                    )

                                return False

            except Exception as whisper_error:
                logger.error(f"Whisper sending failed: {whisper_error}")
                return False

        except Exception as e:
            logger.error(f"Failed to send OAuth invite whisper to {channel_name}: {e}")
            return False

    def generate_oauth_urls(self) -> tuple[str, str]:
        """生成並返回 OAuth 授權 URL"""
        redirect_base = f"http://localhost:{self.port}"

        # Bot Mod 功能 scope（比照 Nightbot）
        bot_scopes = [
            # 聊天核心功能
            "user:read:chat",
            "user:write:chat",
            "channel:bot",
            # Mod 管理功能
            "moderator:read:chatters",
            "moderator:manage:chat_messages",  # 刪除訊息、timeout
            "moderator:manage:banned_users",  # 封鎖管理
            "channel:moderate",
            # 聊天室管理
            "moderator:manage:announcements",
            "moderator:manage:shoutouts",
            "moderator:read:chat_settings",
            # EventSub 事件
            "channel:read:subscriptions",
            "moderator:read:followers",
            "bits:read",
            "channel:read:redemptions",  # Channel Points 兌換事件
            # 通知功能
            "user:read:whispers",
            "user:manage:whispers",
        ]

        # Owner 權限（包含頻道管理）
        owner_scopes = [
            # 繼承 Bot 所有權限
            *bot_scopes,
            # 頻道管理權限
            "channel:manage:moderators",
            "channel:manage:vips",
            "channel:read:vips",
            "channel:read:editors",
            # 進階管理
            "moderator:manage:chat_settings",
            "moderator:manage:blocked_terms",
            "moderator:read:blocked_terms",
            "moderator:manage:automod",
            # 頻道功能
            "channel:manage:raids",
            "channel:read:hype_train",
            "channel:manage:polls",
            "channel:read:polls",
            # 用戶管理
            "user:read:subscriptions",
            "user:read:follows",
        ]

        def create_oauth_url(scopes: list[str], state: str) -> str:
            return (
                f"https://id.twitch.tv/oauth2/authorize"
                f"?client_id={self.client_id}"
                f"&redirect_uri={redirect_base}/oauth"
                f"&response_type=code"
                f"&scope={'+'.join(scopes)}"
                f"&state={state}"
            )

        bot_url = create_oauth_url(bot_scopes, "bot")
        owner_url = create_oauth_url(owner_scopes, "owner")

        return bot_url, owner_url

    def log_oauth_urls(self) -> None:
        """記錄 OAuth URLs 到日誌"""
        bot_url, owner_url = self.generate_oauth_urls()

        logger.info("OAuth authorization URLs:")
        logger.info(f"Bot URL: {bot_url}")
        logger.info(f"Owner URL: {owner_url}")
