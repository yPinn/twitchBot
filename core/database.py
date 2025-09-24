import logging
import time
from pathlib import Path
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


class DatabaseManager:
    """統一資料庫管理器"""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._pool: asyncpg.Pool | None = None
        self._usage_batch: list[tuple[str, str, str]] = []
        self._batch_size = 50
        self._batch_timer: float = 0

    async def initialize(self) -> None:
        """初始化資料庫連接池"""
        try:
            self._pool = await asyncpg.create_pool(self.database_url)
            await self.load_schema()
            logger.debug("Database connection pool created and schema loaded")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    async def close(self) -> None:
        """關閉資料庫連接池"""
        if self._pool:
            await self._flush_usage_batch()
            await self._pool.close()
            logger.info("Database connection closed")

    @property
    def pool(self) -> asyncpg.Pool:
        """取得連接池"""
        if not self._pool:
            raise RuntimeError("Database not initialized")
        return self._pool

    async def load_schema(self) -> None:
        """載入資料庫結構"""
        try:
            schema_path = (
                Path(__file__).parent.parent.parent / "postgres" / "schema.sql"
            )

            with open(schema_path, encoding="utf-8") as f:
                schema_sql = f.read()

            async with self.pool.acquire() as connection:
                await connection.execute(schema_sql)

        except Exception as e:
            logger.error(f"Failed to load schema: {e}")
            raise

    # ========== Token 管理 ==========

    async def check_existing_tokens(self) -> bool:
        """檢查資料庫是否已有 token"""
        try:
            async with self.pool.acquire() as connection:
                rows = await connection.fetch("SELECT COUNT(*) as count FROM tokens")
                return rows[0]["count"] > 0  # type: ignore[no-any-return]
        except Exception:
            return False

    async def add_token(self, user_id: str, token: str, refresh: str) -> None:
        """新增或更新 token"""
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                query = """
                INSERT INTO tokens (user_id, token, refresh)
                VALUES ($1, $2, $3)
                ON CONFLICT(user_id)
                DO UPDATE SET
                    token = EXCLUDED.token,
                    refresh = EXCLUDED.refresh;
                """
                await connection.execute(query, user_id, token, refresh)

    async def load_tokens(self) -> list[dict[str, Any]]:
        """載入所有 tokens"""
        try:
            async with self.pool.acquire() as connection:
                rows = await connection.fetch("SELECT * FROM tokens")
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to load tokens: {e}")
            return []

    async def clear_tokens(self) -> None:
        """清除所有 tokens"""
        async with self.pool.acquire() as connection:
            result = await connection.execute("DELETE FROM tokens")
            logger.info(f"Cleared tokens from database: {result}")

    # ========== 頻道管理 ==========

    async def get_active_channels(self) -> list[dict[str, Any]]:
        """取得所有啟用的頻道"""
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT channel_id, channel_name FROM channels WHERE is_active = true"
            )
            return [dict(row) for row in rows]

    async def get_channels_with_tokens(self) -> list[dict[str, Any]]:
        """取得有對應 token 的頻道列表"""
        try:
            async with self.pool.acquire() as connection:
                rows = await connection.fetch(
                    """SELECT c.channel_id, c.channel_name 
                       FROM channels c 
                       INNER JOIN tokens t ON c.channel_id = t.user_id 
                       WHERE c.is_active = true"""
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get channels with tokens: {e}")
            return []

    async def add_channel(
        self, channel_id: str, channel_name: str, added_by: str | None = None
    ) -> bool:
        """新增頻道到資料庫"""
        try:
            async with self.pool.acquire() as connection:
                async with connection.transaction():
                    result = await connection.execute(
                        """INSERT INTO channels (channel_id, channel_name, added_by) 
                           VALUES ($1, $2, $3) ON CONFLICT (channel_id) DO NOTHING""",
                        channel_id,
                        channel_name,
                        added_by,
                    )
                    await connection.execute(
                        """INSERT INTO channel_settings (channel_id) 
                           VALUES ($1) ON CONFLICT (channel_id) DO NOTHING""",
                        channel_id,
                    )

            if "INSERT" in result:
                logger.info(f"Added channel: {channel_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to add channel: {e}")
            return False

    async def remove_channel(self, channel_id: str) -> bool:
        """移除頻道"""
        try:
            async with self.pool.acquire() as connection:
                result = await connection.execute(
                    "UPDATE channels SET is_active = false WHERE channel_id = $1",
                    channel_id,
                )
                return "UPDATE 1" in result
        except Exception as e:
            logger.error(f"Failed to remove channel: {e}")
            return False

    # ========== 頻道設定 ==========

    async def get_channel_settings(self, channel_id: str) -> dict[str, Any]:
        """取得頻道設定"""
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT prefix, settings FROM channel_settings WHERE channel_id = $1",
                channel_id,
            )
            if row:
                # 確保 settings 是字典類型
                settings = row["settings"] or {}
                if isinstance(settings, str):
                    # 如果是字串，嘗試解析 JSON
                    import json

                    try:
                        settings = json.loads(settings)
                    except (json.JSONDecodeError, TypeError):
                        settings = {}
                return {"prefix": row["prefix"], "settings": settings}
            else:
                return {"prefix": "!", "settings": {}}

    # ========== 自訂指令 ==========

    async def get_custom_command(
        self, channel_id: str, cmd_name: str
    ) -> dict[str, Any] | None:
        """取得自訂指令"""
        try:
            async with self.pool.acquire() as connection:
                row = await connection.fetchrow(
                    """SELECT id, command_name, response_text, cooldown_seconds, user_level, usage_count
                       FROM custom_commands 
                       WHERE channel_id = $1 AND command_name = $2 AND is_active = true""",
                    channel_id,
                    cmd_name,
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get custom commands: {e}")
            return None

    # ========== 使用記錄（批次處理）==========

    async def log_command_usage(
        self, channel_id: str, user_id: str, cmd_name: str
    ) -> None:
        """記錄指令使用（批次版本）"""
        try:
            self._usage_batch.append((channel_id, user_id, cmd_name))

            current_time = time.time()
            if self._batch_timer == 0:
                self._batch_timer = current_time

            batch_full = len(self._usage_batch) >= self._batch_size
            time_exceeded = current_time - self._batch_timer >= 30

            if batch_full or time_exceeded:
                await self._flush_usage_batch()

        except Exception as e:
            logger.error(f"Failed to queue command usage: {e}")

    async def _flush_usage_batch(self) -> None:
        """批次寫入使用記錄"""
        if not self._usage_batch:
            return

        batch_to_process = self._usage_batch.copy()
        self._usage_batch.clear()
        self._batch_timer = 0

        if not batch_to_process:
            return

        try:
            async with self.pool.acquire() as connection:
                async with connection.transaction():
                    for channel_id, user_id, cmd_name in batch_to_process:
                        await connection.execute(
                            """INSERT INTO command_usage (channel_id, user_id, command_name, last_used) 
                               VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
                               ON CONFLICT (channel_id, user_id, command_name) 
                               DO UPDATE SET last_used = CURRENT_TIMESTAMP""",
                            channel_id,
                            user_id,
                            cmd_name,
                        )

                    usage_counts: dict[tuple[str, str], int] = {}
                    for channel_id, _, cmd_name in batch_to_process:
                        key = (channel_id, cmd_name)
                        usage_counts[key] = usage_counts.get(key, 0) + 1

                    for (channel_id, cmd_name), count in usage_counts.items():
                        await connection.execute(
                            "UPDATE custom_commands SET usage_count = usage_count + $3 WHERE channel_id = $1 AND command_name = $2",
                            channel_id,
                            cmd_name,
                            count,
                        )

            logger.debug(f"Flushed {len(batch_to_process)} usage records")

        except Exception as e:
            logger.error(f"Failed to flush usage batch: {e}")
            self._usage_batch = batch_to_process + self._usage_batch

    # ========== 忠誠點數獎勵 ==========

    async def get_available_reward_types(self) -> list[dict[str, Any]]:
        """取得可用的獎勵反應類型"""
        try:
            async with self.pool.acquire() as connection:
                rows = await connection.fetch(
                    "SELECT id, type_key, display_name, description FROM loyalty_reward_types WHERE is_active = true ORDER BY id"
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get reward types: {e}")
            return []

    async def get_reward_mapping(
        self, channel_id: str, reward_id: str
    ) -> dict[str, Any] | None:
        """取得獎勵對應設定"""
        try:
            async with self.pool.acquire() as connection:
                row = await connection.fetchrow(
                    """SELECT clm.*, lrt.type_key, lrt.display_name, lrt.action_config
                       FROM channel_loyalty_mappings clm
                       JOIN loyalty_reward_types lrt ON clm.reward_type_id = lrt.id
                       WHERE clm.channel_id = $1 AND clm.reward_id = $2 AND clm.is_active = true AND lrt.is_active = true""",
                    channel_id,
                    reward_id,
                )
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get reward mapping: {e}")
            return None

    async def get_channel_reward_mappings(
        self, channel_id: str
    ) -> list[dict[str, Any]]:
        """取得頻道的獎勵對應列表"""
        try:
            async with self.pool.acquire() as connection:
                rows = await connection.fetch(
                    """SELECT clm.reward_title, lrt.display_name
                       FROM channel_loyalty_mappings clm
                       JOIN loyalty_reward_types lrt ON clm.reward_type_id = lrt.id
                       WHERE clm.channel_id = $1 AND clm.is_active = true
                       ORDER BY clm.created_at""",
                    channel_id,
                )
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get channel reward mappings: {e}")
            return []

    async def store_pending_mapping(
        self, channel_id: str, reward_title: str, type_id: int
    ) -> None:
        """暫存待處理的對應設定"""
        try:
            async with self.pool.acquire() as connection:
                await connection.execute(
                    """INSERT INTO channel_loyalty_mappings (channel_id, reward_id, reward_title, reward_type_id)
                       VALUES ($1, $2, $3, $4)
                       ON CONFLICT (channel_id, reward_id) DO UPDATE SET
                       reward_title = EXCLUDED.reward_title,
                       reward_type_id = EXCLUDED.reward_type_id""",
                    channel_id,
                    f"pending_{reward_title}",
                    reward_title,
                    type_id,
                )
        except Exception as e:
            logger.error(f"Failed to store pending mapping: {e}")

    async def delete_reward_mapping(self, channel_id: str, reward_title: str) -> bool:
        """刪除獎勵對應"""
        try:
            async with self.pool.acquire() as connection:
                result = await connection.execute(
                    "DELETE FROM channel_loyalty_mappings WHERE channel_id = $1 AND reward_title = $2",
                    channel_id,
                    reward_title,
                )
                return "DELETE 1" in result
        except Exception as e:
            logger.error(f"Failed to delete reward mapping: {e}")
            return False
