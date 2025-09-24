import asyncio
import json
import logging
import random
import time
from typing import Any

import requests
from bs4 import BeautifulSoup
from twitchio.ext import commands

logger = logging.getLogger(__name__)


class LeaderboardComponent(commands.Component):  # type: ignore[misc]
    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self._last_request = 0
        self._cache = None
        self._cache_time = 0

        # 防封鎖配置
        self._user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
        ]

    def get_leaderboard_data(self) -> dict[str, Any] | None:
        """獲取排行榜數據"""
        now = time.time()

        # 檢查 30 秒快取
        if self._cache and (now - self._cache_time) < 30:
            logger.debug("Using cached data")
            return self._cache

        # 頻率限制：3-6 秒間隔
        if now - self._last_request < 3:
            logger.info("Rate limited, using cache")
            return self._cache

        try:
            # 隨機延遲 0.5-1.5 秒
            time.sleep(random.uniform(0.5, 1.5))

            response = requests.get(
                "https://tactics.tools/leaderboards/tw",
                headers={
                    "User-Agent": random.choice(self._user_agents),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
                    "Connection": "keep-alive",
                },
                timeout=8,
            )

            if response.status_code != 200:
                logger.warning(f"HTTP {response.status_code}, using cache")
                return self._cache

            script = BeautifulSoup(response.content, "html.parser").find(
                "script", id="__NEXT_DATA__"
            )
            if not script:
                logger.error("Data element not found, using cache")
                return self._cache

            script_text = getattr(script, "string", None) or script.get_text()
            data = json.loads(script_text)["props"]["pageProps"]["data"]

            # 更新快取和狀態
            self._cache = data
            self._cache_time = int(now)
            self._last_request = int(now)

            entries_count = len(data.get("entries", []))
            logger.info(f"Successfully fetched leaderboard - players: {entries_count}")
            return data  # type: ignore[no-any-return]

        except Exception as e:
            logger.error(f"Scraping failed: {e}, using cache")
            return self._cache

    @commands.command(name="rk")  # type: ignore[misc]
    async def leaderboard_command(
        self, ctx: commands.Context, user_id: str | None = None
    ) -> None:
        logger.debug(
            f"!rk command - {ctx.chatter.name} query: {user_id or 'threshold'}"
        )

        data = await asyncio.get_event_loop().run_in_executor(
            None, self.get_leaderboard_data
        )

        if not data:
            await ctx.send("資料獲取失敗，請稍後再試")
            return

        entries = data.get("entries", [])
        thresholds = data.get("thresholds", [0, 0])

        # 無參數：顯示門檻
        if user_id is None:
            c_lp = thresholds[0] if thresholds else 0
            gm_lp = thresholds[1] if len(thresholds) > 1 else 0
            await ctx.send(f"[TW] C：{c_lp} LP | GM：{gm_lp} LP")
            return

        # 查找玩家
        for player in entries:
            if player.get("playerName", "").lower() == user_id.lower():
                rank = player.get("num")
                lp = player.get("rank", [None, 0])[1]
                await ctx.send(f"{user_id}：{lp} LP #{rank} [TW]")
                logger.debug(f"Query success - {user_id}:{lp} LP #{rank} [TW]")
                return

        await ctx.send(f"該玩家未上榜：{user_id}")


async def setup(bot: Any) -> None:
    await bot.add_component(LeaderboardComponent(bot))
    logger.info("TFT leaderboard component loaded")


async def teardown(bot: Any) -> None:
    logger.info("TFT leaderboard component unloaded")
