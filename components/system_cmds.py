import logging
import random
from typing import Any

from twitchio.ext import commands

logger = logging.getLogger(__name__)


class ChatCommands(commands.Component):  # type: ignore[misc]
    def __init__(self, bot: Any) -> None:
        self.bot = bot

    @commands.command(name="dice")  # type: ignore[misc]
    async def dice_command(self, ctx: commands.Context) -> None:
        """擲骰子指令"""
        result = random.randint(1, 6)
        await ctx.send(f"{ctx.chatter.name} 擲出了 {result}!")

    @commands.command(name="choice")  # type: ignore[misc]
    async def choice_command(self, ctx: commands.Context, *choices: str) -> None:
        """隨機選擇指令"""
        if not choices:
            await ctx.reply("請提供選項！例如：!choice 選項1 選項2 選項3")
            return

        selected = random.choice(choices)
        await ctx.reply(f"從 {len(choices)} 個選項中，我選擇：{selected}")

    @commands.command(name="addch")  # type: ignore[misc]
    async def add_channel_command(
        self, ctx: commands.Context, channel_name: str
    ) -> None:
        """新增頻道到監聽清單 (限系統擁有者且僅限擁有者頻道)"""
        # 統一權限檢查
        if not self._check_admin_permission(ctx):
            await ctx.reply("權限不足 - 此指令僅能由系統擁有者在擁有者頻道中使用")
            return

        try:
            users = await self.bot.fetch_users(logins=[channel_name])
            if not users:
                await ctx.reply(f"❌ 找不到用戶: {channel_name}")
                return

            user = users[0]
            success = await self.bot.add_channel(user.id, user.name, ctx.chatter.id)

            if success:
                # 訂閱基本 EventSub
                try:
                    from twitchio import eventsub

                    chat_subscription = eventsub.ChatMessageSubscription(
                        broadcaster_user_id=user.id, user_id=self.bot.bot_id
                    )
                    await self.bot.subscribe_websocket(payload=chat_subscription)
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        logger.warning(f"EventSub failed for {user.name}: {e}")

                await ctx.reply(f"✅ 已新增頻道: {user.name}")
                await ctx.send(f"請給予 bot 版主權限: /mod {self.bot.user.name}")
                await ctx.send("完整功能請使用 !upgrade 指令進行授權")
            else:
                await ctx.reply("新增頻道失敗")
        except Exception as e:
            await ctx.reply(f"錯誤: {e}")

    @commands.command(name="upgrade")  # type: ignore[misc]
    async def upgrade_channel_command(
        self, ctx: commands.Context, channel_name: str = ""
    ) -> None:
        """啟用頻道進階功能 (需要頻道主本人授權)
        用法:
        - !upgrade (頻道主在自己頻道使用)
        - !upgrade <頻道名> (系統擁有者為指定頻道發送邀請)

        注意: 版主無法使用此指令，因為 OAuth 授權必須由頻道主本人完成
        """
        try:
            # 判斷使用情境
            if channel_name:
                # 指定頻道升級 - 限系統擁有者
                if not self._check_admin_permission(ctx):
                    await ctx.reply("❌ 指定頻道升級僅限系統擁有者使用")
                    return

                target_channel_id, target_channel_name = (
                    await self._get_channel_info_by_name(channel_name)
                )
                if not target_channel_id:
                    await ctx.reply(f"❌ 找不到頻道: {channel_name}")
                    return

                # 系統擁有者模式：為指定頻道發送邀請
                await self._perform_channel_upgrade(
                    ctx, target_channel_id, target_channel_name, is_admin_mode=True
                )
            else:
                # 當前頻道升級 - 限頻道主本人
                if not self._check_broadcaster_permission(ctx):
                    await ctx.reply("❌ 此指令僅限頻道主本人使用")
                    await ctx.send(
                        "💡 OAuth 授權必須由頻道擁有者親自完成，版主無法代為操作"
                    )
                    return

                # 取得當前頻道資訊
                channel_id = (
                    ctx.message.broadcaster.id
                    if ctx.message
                    and hasattr(ctx.message, "broadcaster")
                    and ctx.message.broadcaster
                    else None
                )
                if not channel_id:
                    channel_id = self.bot.owner_id

                target_channel_id = str(channel_id) if channel_id else self.bot.owner_id
                target_channel_name = (
                    getattr(ctx.channel, "name", "")
                    or getattr(ctx.chatter, "name", "")
                    or "unknown"
                )

                # 頻道主模式：為自己頻道升級
                await self._perform_channel_upgrade(
                    ctx, target_channel_id, target_channel_name, is_admin_mode=False
                )

        except Exception as e:
            await ctx.reply(f"❌ 錯誤: {e}")

    async def _get_channel_info_by_name(
        self, channel_name: str
    ) -> tuple[str | None, str]:
        """根據頻道名稱取得頻道資訊"""
        try:
            # 先從資料庫查詢
            async with self.bot.token_database.acquire() as connection:
                channel = await connection.fetchrow(
                    "SELECT channel_id, channel_name FROM channels WHERE channel_name = $1 AND is_active = true",
                    channel_name,
                )

            if channel:
                return channel["channel_id"], channel["channel_name"]

            # 資料庫沒找到，嘗試 API 查詢
            users = await self.bot.fetch_users(logins=[channel_name])
            if users:
                return users[0].id, users[0].name or channel_name

            return None, channel_name
        except Exception:
            return None, channel_name

    async def _perform_channel_upgrade(
        self,
        ctx: commands.Context,
        channel_id: str,
        channel_name: str,
        is_admin_mode: bool = False,
    ) -> None:
        """統一的頻道升級邏輯"""
        # 檢查頻道是否已在監聽清單中
        channels = await self.bot.get_active_channels()
        channel_in_list = any(ch["channel_id"] == channel_id for ch in channels)

        if not channel_in_list:
            await ctx.reply(f"❌ 頻道 {channel_name} 尚未加入監聽清單")
            if is_admin_mode:
                await ctx.send("💡 請先使用 !addch 將頻道加入監聽清單")
            else:
                await ctx.send("💡 請聯繫系統管理員使用 !addch 加入此頻道")
            return

        # 檢查是否已有 token
        async with self.bot.token_database.acquire() as connection:
            token_exists = await connection.fetchval(
                "SELECT user_id FROM tokens WHERE user_id = $1", channel_id
            )

        if token_exists:
            await ctx.reply(f"✅ 頻道 {channel_name} 已啟用完整功能")
            await self._upgrade_to_full_features(channel_id)
            return

        # 發送 OAuth 邀請 - 統一使用最佳策略
        await ctx.reply(f"🔧 正在為頻道 {channel_name} 發送 OAuth 邀請...")

        # 嘗試發送 whisper
        whisper_sent = await self._send_oauth_whisper(channel_name)

        if whisper_sent:
            if is_admin_mode:
                await ctx.reply(f"📧 OAuth 邀請已發送給 @{channel_name}")
                await ctx.send("📋 該頻道主完成授權後將自動啟用完整功能")
            else:
                await ctx.reply("📧 OAuth 邀請已發送，請檢查您的 whisper 完成授權")
        else:
            # Whisper 失敗，提供 OAuth URL
            oauth_url = self.bot.generate_oauth_url_for_channel(channel_name)

            if is_admin_mode:
                await ctx.reply(f"⚠️ 無法發送 whisper 給 @{channel_name}")
                await ctx.send("🔗 OAuth 授權連結（請轉發給該頻道主）：")
                await ctx.send(oauth_url)
                await ctx.send("💡 或請該頻道主在自己頻道使用 !upgrade 指令")
            else:
                await ctx.reply("⚠️ 無法發送 whisper，請使用以下 OAuth 授權連結：")
                await ctx.send(oauth_url)

        await ctx.send(
            "📋 完成授權後將自動啟用完整功能（追蹤、訂閱、贈訂、Channel Points）"
        )

    @commands.command(name="disable")  # type: ignore[misc]
    async def disable_command(self, ctx: commands.Context, command_name: str) -> None:
        """停用指定指令 (限版主/頻道主)"""
        if not self._check_mod_permission(ctx):
            await ctx.reply("權限不足 - 僅限版主或頻道擁有者")
            return

        try:
            # TwitchIO 3.x: 使用 ctx.message.broadcaster.id
            channel_id = (
                ctx.message.broadcaster.id
                if ctx.message
                and hasattr(ctx.message, "broadcaster")
                and ctx.message.broadcaster
                else None
            )
            if not channel_id:
                channel_id = self.bot.owner_id

            # 取得當前設定
            settings = await self.bot.get_channel_settings(channel_id)
            current_settings = settings.get("settings", {})

            # 更新停用指令列表
            disabled_commands = current_settings.get("disabled_commands", [])
            if command_name not in disabled_commands:
                disabled_commands.append(command_name)
                current_settings["disabled_commands"] = disabled_commands

                # 儲存到資料庫（使用 UPSERT 確保記錄存在）
                async with self.bot.token_database.acquire() as connection:
                    await connection.execute(
                        """INSERT INTO channel_settings (channel_id, settings) 
                           VALUES ($2, $1) 
                           ON CONFLICT (channel_id) 
                           DO UPDATE SET settings = EXCLUDED.settings""",
                        current_settings,
                        channel_id,
                    )

                # 清除快取
                self.bot.clear_channel_settings_cache(channel_id)
                await ctx.reply(f"✅ 已停用指令: {command_name}")
            else:
                await ctx.reply(f"指令 {command_name} 已經是停用狀態")

        except Exception as e:
            await ctx.reply(f"錯誤: {e}")

    @commands.command(name="enable")  # type: ignore[misc]
    async def enable_command(self, ctx: commands.Context, command_name: str) -> None:
        """啟用指定指令 (限版主/頻道主)"""
        if not self._check_mod_permission(ctx):
            await ctx.reply("權限不足 - 僅限版主或頻道擁有者")
            return

        try:
            # TwitchIO 3.x: 使用 ctx.message.broadcaster.id
            channel_id = (
                ctx.message.broadcaster.id
                if ctx.message
                and hasattr(ctx.message, "broadcaster")
                and ctx.message.broadcaster
                else None
            )
            if not channel_id:
                channel_id = self.bot.owner_id

            # 取得當前設定
            settings = await self.bot.get_channel_settings(channel_id)
            current_settings = settings.get("settings", {})

            # 更新停用指令列表
            disabled_commands = current_settings.get("disabled_commands", [])
            if command_name in disabled_commands:
                disabled_commands.remove(command_name)
                current_settings["disabled_commands"] = disabled_commands

                # 儲存到資料庫（使用 UPSERT 確保記錄存在）
                async with self.bot.token_database.acquire() as connection:
                    await connection.execute(
                        """INSERT INTO channel_settings (channel_id, settings) 
                           VALUES ($2, $1) 
                           ON CONFLICT (channel_id) 
                           DO UPDATE SET settings = EXCLUDED.settings""",
                        current_settings,
                        channel_id,
                    )

                # 清除快取
                self.bot.clear_channel_settings_cache(channel_id)
                await ctx.reply(f"✅ 已啟用指令: {command_name}")
            else:
                await ctx.reply(f"指令 {command_name} 已經是啟用狀態")

        except Exception as e:
            await ctx.reply(f"錯誤: {e}")

    @commands.command(name="commands")  # type: ignore[misc]
    async def list_commands(self, ctx: commands.Context) -> None:
        """顯示所有可用指令及其狀態"""
        try:
            # TwitchIO 3.x: 使用 ctx.message.broadcaster.id
            channel_id = (
                ctx.message.broadcaster.id
                if ctx.message
                and hasattr(ctx.message, "broadcaster")
                and ctx.message.broadcaster
                else None
            )
            if not channel_id:
                channel_id = self.bot.owner_id

            # 取得停用指令列表
            settings = await self.bot.get_channel_settings(channel_id)
            disabled_commands = settings.get("settings", {}).get(
                "disabled_commands", []
            )

            # 定義所有系統指令
            all_commands = {
                "dice": "擲骰子",
                "choice": "隨機選擇",
                "rk": "TFT 排名查詢",
                "translate": "翻譯文字",
                "upgrade": "啟用進階功能",
            }

            # 建立狀態列表
            enabled_cmds = []
            disabled_cmds = []

            for cmd, desc in all_commands.items():
                if cmd in disabled_commands:
                    disabled_cmds.append(f"❌ {cmd} - {desc}")
                else:
                    enabled_cmds.append(f"✅ {cmd} - {desc}")

            # 組合回應
            response = "📋 指令狀態："
            if enabled_cmds:
                response += f"\n\n啟用: {', '.join([cmd.split(' - ')[0] for cmd in enabled_cmds])}"
            if disabled_cmds:
                response += f"\n停用: {', '.join([cmd.split(' - ')[0] for cmd in disabled_cmds])}"

            response += "\n\n使用 !disable <指令> 或 !enable <指令> 來管理"

            await ctx.reply(response)

        except Exception as e:
            await ctx.reply(f"錯誤: {e}")

    async def _upgrade_to_full_features(self, channel_id: str) -> None:
        """升級頻道到完整功能"""
        try:
            async with self.bot.token_database.acquire() as connection:
                channel = await connection.fetchrow(
                    "SELECT channel_name FROM channels WHERE channel_id = $1",
                    channel_id,
                )

            if not channel:
                return

            # 訂閱完整事件
            await self.bot.subscribe_eventsub(channel_id, advanced_only=True)
            logger.info(f"Full features upgraded for {channel['channel_name']}")

        except Exception as e:
            logger.error(f"Upgrade failed for channel {channel_id}: {e}")

    @commands.command(name="delch")  # type: ignore[misc]
    async def remove_channel_command(
        self, ctx: commands.Context, channel_name: str
    ) -> None:
        """移除頻道監聽 (限系統擁有者且僅限擁有者頻道)"""
        # 統一權限檢查
        if not self._check_admin_permission(ctx):
            await ctx.reply("權限不足 - 此指令僅能由系統擁有者在擁有者頻道中使用")
            return

        try:
            # 先嘗試從資料庫查詢頻道（避免依賴 API）
            async with self.bot.token_database.acquire() as connection:
                channel = await connection.fetchrow(
                    "SELECT channel_id, channel_name FROM channels WHERE channel_name = $1 AND is_active = true",
                    channel_name,
                )

            if channel:
                # 從資料庫找到，直接移除
                success = await self.bot.remove_channel(channel["channel_id"])
                if success:
                    await ctx.reply(f"✅ 已移除頻道: {channel_name}")
                else:
                    await ctx.reply("移除頻道失敗")
                return

            # 資料庫沒找到，嘗試 API 查詢
            users = await self.bot.fetch_users(logins=[channel_name])
            if not users:
                await ctx.reply(f"頻道不存在或已從監聽清單移除: {channel_name}")
                return

            user = users[0]
            success = await self.bot.remove_channel(user.id)

            if success:
                await ctx.reply(f"已移除頻道: {user.name}")
            else:
                await ctx.reply("移除失敗")
        except Exception as e:
            await ctx.reply(f"錯誤: {e}")

    @commands.command(name="ch")  # type: ignore[misc]
    async def list_channels_command(self, ctx: commands.Context) -> None:
        """列出所有監聽中的頻道"""
        try:
            channels = await self.bot.get_active_channels()
            if not channels:
                await ctx.reply("📭 目前沒有監聽任何頻道")
                return

            channel_list = [f"{ch['channel_name']}" for ch in channels]
            await ctx.reply(
                f'📺 監聽中的頻道 ({len(channels)}): {", ".join(channel_list)}'
            )
        except Exception as e:
            await ctx.reply(f"❌ 錯誤: {e}")

    @commands.command(name="addcmd")  # type: ignore[misc]
    async def add_custom_command(
        self, ctx: commands.Context, name: str, *, response: str
    ) -> None:
        """新增自訂指令"""
        if not self._check_mod_permission(ctx):
            await ctx.reply("權限不足 - 僅限版主或頻道擁有者")
            return

        if not name or not response:
            await ctx.reply("用法: !addcmd <指令名稱> <回應內容>")
            return

        name = name.lower().lstrip("!")

        # 防止覆蓋系統指令
        system_commands = [
            "addcmd",
            "editcmd",
            "delcmd",
            "cmdlist",
            "cmdinfo",
            "dice",
            "choice",
            "addch",
            "delch",
            "ch",
            "setprefix",
            "eventsub",
            "upgrade",
        ]
        if name in system_commands:
            await ctx.reply(f"無法覆蓋系統指令: {name}")
            return

        try:
            channel_id = (
                ctx.broadcaster.id if hasattr(ctx, "broadcaster") else self.bot.owner_id
            )
            async with self.bot.token_database.acquire() as connection:
                result = await connection.execute(
                    """INSERT INTO custom_commands (channel_id, command_name, response_text) 
                       VALUES ($1, $2, $3)
                       ON CONFLICT (channel_id, command_name) 
                       DO UPDATE SET response_text = EXCLUDED.response_text, updated_at = CURRENT_TIMESTAMP""",
                    channel_id,
                    name,
                    response,
                )

                if "INSERT" in result:
                    await ctx.reply(f"✅ 新增指令: !{name}")
                else:
                    await ctx.reply(f"✅ 更新指令: !{name}")

                # 重載該頻道的指令緩存
                await self._reload_custom_commands(channel_id)

        except Exception as e:
            await ctx.reply(f"❌ 新增指令失敗: {e}")

    @commands.command(name="editcmd")  # type: ignore[misc]
    async def edit_custom_command(
        self, ctx: commands.Context, name: str, *, response: str
    ) -> None:
        """編輯自訂指令"""
        if not self._check_mod_permission(ctx):
            await ctx.reply("權限不足 - 僅限版主或頻道擁有者")
            return

        if not name or not response:
            await ctx.reply("用法: !editcmd <指令名稱> <新回應內容>")
            return

        name = name.lower().lstrip("!")

        try:
            channel_id = (
                ctx.broadcaster.id if hasattr(ctx, "broadcaster") else self.bot.owner_id
            )
            async with self.bot.token_database.acquire() as connection:
                result = await connection.execute(
                    """UPDATE custom_commands 
                       SET response_text = $3, updated_at = CURRENT_TIMESTAMP
                       WHERE channel_id = $1 AND command_name = $2 AND is_active = true""",
                    channel_id,
                    name,
                    response,
                )

                if "UPDATE 1" in result:
                    await ctx.reply(f"✅ 已更新指令: !{name}")
                    # 重載該頻道的指令緩存
                    await self._reload_custom_commands(channel_id)
                else:
                    await ctx.reply(f"❌ 指令不存在: !{name}")

        except Exception as e:
            await ctx.reply(f"❌ 編輯指令失敗: {e}")

    @commands.command(name="delcmd")  # type: ignore[misc]
    async def delete_custom_command(self, ctx: commands.Context, name: str) -> None:
        """刪除自訂指令"""
        if not self._check_mod_permission(ctx):
            await ctx.reply("權限不足 - 僅限版主或頻道擁有者")
            return

        if not name:
            await ctx.reply("用法: !delcmd <指令名稱>")
            return

        name = name.lower().lstrip("!")

        try:
            channel_id = (
                ctx.broadcaster.id if hasattr(ctx, "broadcaster") else self.bot.owner_id
            )
            async with self.bot.token_database.acquire() as connection:
                result = await connection.execute(
                    "UPDATE custom_commands SET is_active = false WHERE channel_id = $1 AND command_name = $2",
                    channel_id,
                    name,
                )

                if "UPDATE 1" in result:
                    await ctx.reply(f"✅ 已刪除指令: !{name}")
                    # 重載該頻道的指令緩存
                    await self._reload_custom_commands(channel_id)
                else:
                    await ctx.reply(f"❌ 指令不存在: !{name}")

        except Exception as e:
            await ctx.reply(f"❌ 刪除指令失敗: {e}")

    @commands.command(name="cmdlist")  # type: ignore[misc]
    async def list_custom_commands(self, ctx: commands.Context) -> None:
        """列出所有指令 (全域指令 + 自訂指令)"""
        try:
            # 定義全域通用指令
            global_commands_basic = [
                "dice",
                "choice",
                "cmdlist",
                "cmdinfo",
            ]  # 基礎指令 (所有人)
            global_commands_mod = [
                "addcmd",
                "editcmd",
                "delcmd",
                "setprefix",
                "upgrade",
            ]  # 版主管理指令 (CUD操作)
            global_commands_admin = [
                "addch",
                "delch",
                "ch",
                "eventsub",
            ]  # 系統管理指令 (owner專用)

            # 根據權限組建可用指令清單
            available_global = global_commands_basic[:]

            # 版主權限指令
            if (
                getattr(ctx.chatter, "is_mod", False)
                or ctx.chatter.id == self.bot.owner_id
            ):
                available_global.extend(global_commands_mod)

            # 系統擁有者專用指令
            if ctx.chatter.id == self.bot.owner_id:
                available_global.extend(global_commands_admin)

            # 取得該頻道的自訂指令
            channel_id = (
                ctx.broadcaster.id if hasattr(ctx, "broadcaster") else self.bot.owner_id
            )
            async with self.bot.token_database.acquire() as connection:
                rows = await connection.fetch(
                    """SELECT command_name, usage_count FROM custom_commands 
                       WHERE channel_id = $1 AND is_active = true 
                       ORDER BY usage_count DESC, command_name""",
                    channel_id,
                )

            # 組建回應訊息
            response_parts = []

            # 全域指令
            global_list = [f"!{cmd}" for cmd in sorted(available_global)]
            response_parts.append(
                f"🌐 全域指令 ({len(global_list)}): {', '.join(global_list)}"
            )

            # 自訂指令
            if rows:
                custom_list = [
                    f"!{row['command_name']}({row['usage_count']})" for row in rows
                ]
                response_parts.append(
                    f"🎯 自訂指令 ({len(rows)}): {', '.join(custom_list)}"
                )
            else:
                response_parts.append("🎯 自訂指令 (0): 無")

            # 發送回應 (分兩條訊息避免過長)
            for part in response_parts:
                await ctx.reply(part)

        except Exception as e:
            await ctx.reply(f"❌ 取得指令清單失敗: {e}")

    @commands.command(name="cmdinfo")  # type: ignore[misc]
    async def command_info(self, ctx: commands.Context, name: str) -> None:
        """顯示指令詳細資訊"""
        if not name:
            await ctx.reply("用法: !cmdinfo <指令名稱>")
            return

        name = name.lower().lstrip("!")

        try:
            channel_id = (
                ctx.broadcaster.id if hasattr(ctx, "broadcaster") else self.bot.owner_id
            )
            async with self.bot.token_database.acquire() as connection:
                row = await connection.fetchrow(
                    """SELECT command_name, response_text, cooldown_seconds, user_level, usage_count, created_at
                       FROM custom_commands 
                       WHERE channel_id = $1 AND command_name = $2 AND is_active = true""",
                    channel_id,
                    name,
                )

                if not row:
                    await ctx.reply(f"❌ 指令不存在: !{name}")
                    return

                info = (
                    f"📝 指令: !{row['command_name']} | "
                    f"冷卻: {row['cooldown_seconds']}s | "
                    f"權限: {row['user_level']} | "
                    f"使用: {row['usage_count']}次"
                )
                await ctx.reply(info)

        except Exception as e:
            await ctx.reply(f"❌ 取得指令資訊失敗: {e}")

    @commands.command(name="setprefix")  # type: ignore[misc]
    async def set_prefix_command(self, ctx: commands.Context, prefix: str) -> None:
        """設定頻道指令前綴 (限版主)"""
        if not self._check_mod_permission(ctx):
            await ctx.reply("權限不足 - 僅限版主或頻道擁有者")
            return

        if not prefix or len(prefix) > 5:
            await ctx.reply("前綴長度必須為 1-5 個字元")
            return

        try:
            channel_id = (
                ctx.broadcaster.id if hasattr(ctx, "broadcaster") else self.bot.owner_id
            )
            async with self.bot.token_database.acquire() as connection:
                await connection.execute(
                    """INSERT INTO channel_settings (channel_id, prefix) 
                       VALUES ($1, $2)
                       ON CONFLICT (channel_id) 
                       DO UPDATE SET prefix = EXCLUDED.prefix""",
                    channel_id,
                    prefix,
                )

            # 清除頻道設定快取
            self.bot.clear_channel_settings_cache(channel_id)
            await ctx.reply(f"✅ 已設定前綴為: {prefix}")

        except Exception as e:
            await ctx.reply(f"❌ 設定前綴失敗: {e}")

    @commands.command(name="eventsub")  # type: ignore[misc]
    async def eventsub_status_command(self, ctx: commands.Context) -> None:
        """檢查 EventSub 訂閱狀態 (限系統擁有者)"""
        if not self._check_admin_permission(ctx):
            await ctx.reply("權限不足 - 此指令僅能由系統擁有者在擁有者頻道中使用")
            return

        try:
            limits = await self.bot.check_eventsub_limits()
            if limits:
                total = limits.get("total", 0)
                total_cost = limits.get("total_cost", 0)
                max_cost = limits.get("max_total_cost", 10000)
                remaining = limits.get("remaining_cost", 0)

                usage_pct = (total_cost / max_cost * 100) if max_cost > 0 else 0

                status = (
                    f"📊 EventSub 狀態: {total} 訂閱 | "
                    f"成本: {total_cost}/{max_cost} ({usage_pct:.1f}%) | "
                    f"剩餘: {remaining}"
                )

                if remaining < 100:
                    status += " ⚠️ 接近限制"
                elif remaining < 500:
                    status += " ⚡ 成本偏高"
                else:
                    status += " ✅ 正常"

                await ctx.reply(status)
            else:
                await ctx.reply("❌ 無法取得 EventSub 狀態")

        except Exception as e:
            await ctx.reply(f"❌ 檢查狀態失敗: {e}")

    @commands.command(name="testwhisper")  # type: ignore[misc]
    async def test_whisper_command(
        self,
        ctx: commands.Context,
        target_user: str,
        *,
        message: str = "這是一條測試 whisper 訊息 🤖",
    ) -> None:
        """測試 whisper 功能 (限系統擁有者)
        用法: !testwhisper <用戶名> [自訂訊息]
        """
        if not self._check_admin_permission(ctx):
            await ctx.reply("權限不足 - 此指令僅能由系統擁有者在擁有者頻道中使用")
            return

        if not target_user:
            await ctx.reply("用法: !testwhisper <用戶名> [自訂訊息]")
            return

        try:
            await ctx.reply(f"🔧 正在測試發送 whisper 給 @{target_user}...")

            # 診斷資訊
            await ctx.send("🔍 開始 whisper 診斷...")

            # 檢查用戶是否存在
            users = await self.bot.fetch_users(logins=[target_user])
            if not users:
                await ctx.reply(f"❌ 用戶 @{target_user} 不存在")
                return

            await ctx.send(f"✅ 找到用戶: {users[0].name} (ID: {users[0].id})")

            # 檢查 bot 用戶資訊
            bot_users = await self.bot.fetch_users(ids=[self.bot.bot_id])
            if not bot_users:
                await ctx.reply("❌ 無法取得 bot 用戶資訊")
                return

            await ctx.send(f"✅ Bot 用戶: {bot_users[0].name} (ID: {self.bot.bot_id})")

            # 檢查可用的 whisper 方法
            available_methods = []
            if hasattr(self.bot, "create_whisper"):
                available_methods.append("create_whisper")
            if hasattr(bot_users[0], "send_whisper"):
                available_methods.append("user.send_whisper")

            await ctx.send(
                f"🔧 可用方法: {', '.join(available_methods) if available_methods else 'HTTP API only'}"
            )

            # 嘗試發送測試 whisper
            whisper_sent = await self._send_test_whisper(target_user, message)

            if whisper_sent:
                await ctx.reply(f"✅ 測試 whisper 發送成功給 @{target_user}")
                await ctx.send(f'📧 訊息內容: "{message}"')
            else:
                await ctx.reply(f"❌ 測試 whisper 發送失敗給 @{target_user}")
                await ctx.send("🔍 常見問題:")
                await ctx.send("• Bot 帳號需要驗證手機號碼")
                await ctx.send("• 目標用戶的 whisper 設定可能關閉")
                await ctx.send("• 檢查後臺日誌獲取詳細錯誤")

        except Exception as e:
            await ctx.reply(f"❌ 測試異常: {str(e)}")
            logger.error(f"testwhisper 指令異常: {e}")

    @commands.command(name="checkscopes")  # type: ignore[misc]
    async def check_scopes_command(self, ctx: commands.Context) -> None:
        """檢查 bot 的 OAuth scopes (限系統擁有者)"""
        if not self._check_admin_permission(ctx):
            await ctx.reply("權限不足 - 此指令僅能由系統擁有者在擁有者頻道中使用")
            return

        try:
            await ctx.reply("🔍 正在檢查 bot 的 OAuth scopes...")

            # 從資料庫取得 bot 的 token
            async with self.bot.token_database.acquire() as connection:
                token_row = await connection.fetchrow(
                    "SELECT token FROM tokens WHERE user_id = $1 LIMIT 1",
                    self.bot.bot_id,
                )

            if not token_row:
                await ctx.reply("❌ 找不到 bot 的 access token")
                return

            access_token = token_row["token"]

            # 使用 Twitch API 驗證 token 並取得 scopes
            import os

            import aiohttp

            client_id = os.getenv("CLIENT_ID")
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Client-Id": client_id,
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://id.twitch.tv/oauth2/validate", headers=headers
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        scopes = data.get("scopes", [])

                        await ctx.reply(f"✅ Token 有效，共 {len(scopes)} 個 scopes")

                        # 檢查關鍵的 whisper 權限
                        whisper_scopes = [s for s in scopes if "whisper" in s]
                        if whisper_scopes:
                            await ctx.send(
                                f"🔊 Whisper 權限: {', '.join(whisper_scopes)}"
                            )
                        else:
                            await ctx.send(
                                "❌ 缺少 whisper 權限 (user:manage:whispers)"
                            )

                        # 顯示所有 scopes
                        scope_chunks = []
                        chunk_size = 10
                        for i in range(0, len(scopes), chunk_size):
                            chunk = scopes[i : i + chunk_size]
                            scope_chunks.append(", ".join(chunk))

                        for i, chunk in enumerate(scope_chunks, 1):
                            await ctx.send(
                                f"📋 Scopes ({i}/{len(scope_chunks)}): {chunk}"
                            )
                    else:
                        await ctx.reply(f"❌ Token 驗證失敗 ({response.status})")

        except Exception as e:
            await ctx.reply(f"❌ 檢查失敗: {str(e)}")
            logger.error(f"checkscopes 指令異常: {e}")

    @commands.command(name="whisperinfo")  # type: ignore[misc]
    async def whisper_info_command(self, ctx: commands.Context) -> None:
        """顯示 whisper 功能要求和設定資訊 (限系統擁有者)"""
        if not self._check_admin_permission(ctx):
            await ctx.reply("權限不足 - 此指令僅能由系統擁有者在擁有者頻道中使用")
            return

        try:
            await ctx.reply("🔊 Twitch Whisper 功能要求:")
            await ctx.send("1️⃣ Bot 帳號需要 user:manage:whispers scope ✅")
            await ctx.send("2️⃣ Bot 帳號必須驗證手機號碼 ❓")
            await ctx.send("3️⃣ 目標用戶允許接收 whisper ❓")
            await ctx.send("")
            await ctx.send("🔧 如何驗證手機號碼:")
            await ctx.send("• 登入 https://twitch.tv/settings/security")
            await ctx.send("• 找到 'Phone Number' 選項")
            await ctx.send("• 添加並驗證手機號碼")
            await ctx.send("")
            await ctx.send("⚠️ 注意: 沒有驗證手機號碼將導致 401 錯誤")
            await ctx.send("✅ 驗證完成後請使用 !testwhisper 重新測試")

        except Exception as e:
            await ctx.reply(f"❌ 顯示資訊失敗: {str(e)}")

    @commands.command(name="testoauth")  # type: ignore[misc]
    async def test_oauth_whisper_command(
        self, ctx: commands.Context, channel_name: str
    ) -> None:
        """測試 OAuth whisper 發送給指定頻道 (限系統擁有者)"""
        if not self._check_admin_permission(ctx):
            await ctx.reply("權限不足 - 此指令僅能由系統擁有者在擁有者頻道中使用")
            return

        if not channel_name:
            await ctx.reply("用法: !testoauth <頻道名稱>")
            return

        try:
            await ctx.reply(f"🔧 測試發送 OAuth whisper 給 @{channel_name}...")

            # 驗證目標用戶存在
            users = await self.bot.fetch_users(logins=[channel_name])
            if not users:
                await ctx.reply(f"❌ 找不到用戶: {channel_name}")
                return

            target_user = users[0]
            await ctx.send(f"✅ 目標用戶: {target_user.name} (ID: {target_user.id})")

            # 發送 OAuth whisper
            oauth_sent = await self._send_oauth_whisper(channel_name)

            if oauth_sent:
                await ctx.reply(f"✅ OAuth whisper 發送成功給 @{channel_name}")
                await ctx.send(
                    f"📧 Whisper 已發送給: {target_user.name} ({target_user.id})"
                )
            else:
                await ctx.reply(f"❌ OAuth whisper 發送失敗給 @{channel_name}")
                await ctx.send("💡 請檢查後臺日誌獲取詳細錯誤")

        except Exception as e:
            await ctx.reply(f"❌ 測試失敗: {str(e)}")
            logger.error(f"testoauth 指令異常: {e}")

    async def _send_test_whisper(self, target_user: str, message: str) -> bool:
        """發送測試 whisper 的輔助方法"""
        try:
            # 使用與 oauth_manager 相同的 whisper 實現邏輯
            # 取得目標用戶資訊
            users = await self.bot.fetch_users(logins=[target_user])
            if not users:
                logger.error(f"無法找到用戶: {target_user}")
                return False

            target_user_obj = users[0]

            # 取得 bot 用戶資訊
            bot_users = await self.bot.fetch_users(ids=[self.bot.bot_id])
            if not bot_users:
                logger.error("無法取得 bot 用戶資訊")
                return False

            bot_user = bot_users[0]

            # 嘗試發送 whisper - 使用 TwitchIO 3.x 的方法
            try:
                # 方法1：使用 create_whisper (如果存在)
                if hasattr(self.bot, "create_whisper"):
                    await self.bot.create_whisper(
                        from_user_id=self.bot.bot_id,
                        to_user_id=target_user_obj.id,
                        message=message,
                    )
                    logger.info(
                        f"Whisper 透過 create_whisper 發送成功：Bot({self.bot.bot_id}) → {target_user}({target_user_obj.id})"
                    )
                    return True

                # 方法2：使用用戶物件的 send_whisper 方法
                elif hasattr(bot_user, "send_whisper"):
                    await bot_user.send_whisper(
                        to_user=target_user_obj, message=message
                    )
                    logger.info(
                        f"Whisper 透過 user.send_whisper 發送成功：Bot({self.bot.bot_id}) → {target_user}({target_user_obj.id})"
                    )
                    return True

                # 方法3：使用 HTTP API 直接發送
                else:
                    import os

                    import aiohttp

                    # 取得存取令牌（從 bot 的 token 管理中）
                    async with self.bot.token_database.acquire() as connection:
                        token_row = await connection.fetchrow(
                            "SELECT token FROM tokens WHERE user_id = $1 LIMIT 1",
                            self.bot.bot_id,
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

                    url = f"https://api.twitch.tv/helix/whispers?from_user_id={self.bot.bot_id}&to_user_id={target_user_obj.id}"

                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            url, headers=headers, json=data
                        ) as response:
                            if response.status == 204:
                                logger.info(
                                    f"Whisper 透過 HTTP API 發送成功：Bot({self.bot.bot_id}) → {target_user}({target_user_obj.id})"
                                )
                                return True
                            else:
                                error_text = await response.text()
                                error_msg = f"HTTP API whisper 失敗 ({response.status}): {error_text}"

                                # 特殊錯誤處理
                                if response.status == 401:
                                    if "verified phone number" in error_text:
                                        logger.error(
                                            "❌ Bot 帳號需要驗證手機號碼才能發送 whisper"
                                        )
                                    else:
                                        logger.error(
                                            f"❌ 權限不足或 token 無效: {error_text}"
                                        )
                                elif response.status == 400:
                                    logger.error(
                                        f"❌ 請求格式錯誤或用戶不允許 whisper: {error_text}"
                                    )
                                elif response.status == 403:
                                    logger.error(
                                        f"❌ Bot 被目標用戶封鎖或無權限: {error_text}"
                                    )
                                else:
                                    logger.error(error_msg)

                                return False

            except Exception as whisper_error:
                logger.error(f"whisper 發送異常: {whisper_error}")
                return False

        except Exception as e:
            logger.error(f"_send_test_whisper 錯誤: {e}")
            return False

    async def _send_oauth_whisper(self, channel_name: str) -> bool:
        """統一的 OAuth whisper 發送方法，使用與 testwhisper 相同的邏輯"""
        try:
            # 生成 OAuth URL
            oauth_url = self.bot.generate_oauth_url_for_channel(channel_name)

            # 構建 whisper 訊息
            message = (
                f"🤖 嗨 {channel_name}！為了讓 Niibot 在你的頻道提供完整功能 "
                f"(如追蹤通知、訂閱事件等)，需要你的授權。\n\n"
                f"請點擊此連結完成授權：{oauth_url}\n\n"
                f"授權後 Niibot 就能在你的頻道正常運作所有進階功能了！"
            )

            # 使用與 testwhisper 相同的發送邏輯
            return await self._send_test_whisper(channel_name, message)

        except Exception as e:
            logger.error(f"_send_oauth_whisper 錯誤: {e}")
            return False

    def _check_admin_permission(self, ctx: commands.Context) -> bool:
        """檢查管理員權限 (owner 在 owner 頻道)"""
        if ctx.chatter.id != self.bot.owner_id:
            return False

        # TwitchIO 3.x: 使用 ctx.message.broadcaster.id
        channel_id = (
            ctx.message.broadcaster.id
            if ctx.message
            and hasattr(ctx.message, "broadcaster")
            and ctx.message.broadcaster
            else None
        )
        return channel_id == self.bot.owner_id

    def _check_broadcaster_permission(self, ctx: commands.Context) -> bool:
        """檢查頻道主權限 (僅限頻道擁有者本人或系統擁有者)"""
        # 系統擁有者永遠有權限
        if ctx.chatter.id == self.bot.owner_id:
            return True

        # 取得當前頻道 ID
        channel_id = (
            ctx.message.broadcaster.id
            if ctx.message
            and hasattr(ctx.message, "broadcaster")
            and ctx.message.broadcaster
            else None
        )

        # 檢查是否為頻道擁有者本人
        return bool(channel_id and str(ctx.chatter.id) == str(channel_id))

    def _check_mod_permission(self, ctx: commands.Context) -> bool:
        """檢查版主權限"""
        # 系統擁有者
        if ctx.chatter.id == self.bot.owner_id:
            return True

        # 頻道擁有者
        # TwitchIO 3.x: 使用 ctx.message.broadcaster.id
        channel_id = (
            ctx.message.broadcaster.id
            if ctx.message
            and hasattr(ctx.message, "broadcaster")
            and ctx.message.broadcaster
            else None
        )
        if channel_id and ctx.chatter.id == channel_id:
            return True

        # 版主
        if hasattr(ctx.chatter, "badges") and ctx.chatter.badges:
            for badge in ctx.chatter.badges:
                if badge.name in ["moderator", "broadcaster"]:
                    return True

        return False

    async def _reload_custom_commands(self, channel_id: str) -> None:
        """重載特定頻道的自訂指令緩存"""
        try:
            # 通過 bot 的統一 API 重載
            await self.bot.reload_custom_commands(channel_id)
        except Exception:
            # 靜默失敗，不影響正常操作
            pass


# 模組載入函數


async def setup(bot: Any) -> None:
    await bot.add_component(ChatCommands(bot))


# 模組卸載函數 (可選)


async def teardown(bot: Any) -> None:
    pass
