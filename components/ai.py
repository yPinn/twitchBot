import logging
import os
from typing import Any

from openai import AsyncOpenAI
from twitchio.ext import commands

logger = logging.getLogger(__name__)


class AIComponent(commands.Component):  # type: ignore[misc]
    def __init__(self, bot: Any) -> None:
        self.bot = bot

        # 使用異步客戶端
        self.openai_client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
        )

        # AI 設置 - 優化回應速度
        self.ai_model = "google/gemma-3n-e4b-it:free"
        self.max_tokens = 69
        self.temperature = 0.6

        # Twitch 禁詞列表
        self.banned_words = {
            # 種族歧視詞彙
            "nigger",
            "nigga",
            "chink",
            "gook",
            "spic",
            "kike",
            "支那",
            "黑鬼",
            "尼哥",
            # 暴力威脅
            "kys",
            "kill yourself",
            "去死",
            "自殺",
        }

    async def _get_ai_response(self, prompt: str, ctx: commands.Context) -> str | None:
        """獲取 AI 回應"""
        try:
            # 使用異步調用
            completion = await self.openai_client.chat.completions.create(
                extra_headers={
                    # 動態獲取
                    "HTTP-Referer": f"https://twitch.tv/{ctx.broadcaster.name}",
                    "X-Title": f"{ctx.broadcaster.name} AI Bot",
                },
                model=self.ai_model,
                messages=[
                    {
                        "role": "user",
                        "content": f"""
                                    你是 {ctx.broadcaster.display_name} 的 Twitch 聊天小助手。
                                    你的個性：毒舌搞笑、嘴砲風格，但不會帶惡意。
                                    請用【繁體中文】回覆觀眾，回答限制在 2-3 句，語氣要有點調侃或嗆人感，保持聊天室的歡樂氛圍。
                                    允許適度使用 Twitch 表情符號（像是 KEKW、LUL），但不要洗版。
                                    避免政治、劇透或敏感話題。

                                    觀眾提問：{prompt}
                                    """,
                    }
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                timeout=8.0,  # 降低超時時間提升響應
            )

            response = completion.choices[0].message.content
            return response.strip() if response else None

        except TimeoutError:
            logger.warning("AI API request timeout")
            return "AI 回應超時，請稍後再試 ⏱️"
        except Exception as e:
            # 根據錯誤類型給出不同回應
            if "rate_limit" in str(e).lower():
                logger.warning(f"API rate limit: {e}")
                return "API 使用量已達上限，請稍後再試 🚦"
            elif "unauthorized" in str(e).lower():
                logger.error(f"API authentication error: {e}")
                return "AI 服務暫時不可用 🔧"
            else:
                logger.error(f"AI API unknown error: {e}")
                return "AI 暫時無法回應，請稍後再試 😅"

    def _contains_banned_words(self, text: str) -> bool:
        """檢查文本是否包含禁詞 - 優化版本"""
        text_lower = text.lower()
        # 使用 set 進行快速查找
        return any(banned_word in text_lower for banned_word in self.banned_words)

    @commands.command(name="ai")  # type: ignore[misc]
    # type: ignore[misc]
    @commands.cooldown(rate=1, per=8, key=commands.BucketType.user)  # 降低冷卻時間
    async def ai_command(
        self, ctx: commands.Context, *, prompt: str | None = None
    ) -> None:
        """AI 指令：!ai 你的問題"""
        try:
            # 參數驗證
            if not prompt:
                await ctx.reply("使用方法: !ai 你的問題")
                return

            if len(prompt) > 500:
                await ctx.reply("問題太長了，請縮短到 500 字以內！")
                return

            # 內容過濾 - 檢查禁詞
            if self._contains_banned_words(prompt):
                await ctx.reply("請使用友善和尊重的語言，避免歧視或仇恨言論 😊")
                return

            # 獲取 AI 回應 - 傳入 ctx 參數
            ai_response = await self._get_ai_response(prompt, ctx)

            # 檢查 AI 回應是否包含禁詞
            if ai_response and self._contains_banned_words(ai_response):
                await ctx.reply("AI 回應包含不當內容，已過濾 🚫")
                return

            if ai_response:
                await ctx.reply(ai_response)
                logger.debug(f"{ctx.chatter.name} used AI: {prompt[:50]}...")
            else:
                await ctx.reply("AI 沒有回應，請稍後再試")

        except commands.CommandOnCooldown as e:
            # 自定義冷卻提示
            await ctx.reply(
                f"AI 指令冷卻中，請等待 {getattr(e, 'retry_after', 0):.0f} 秒 ⏰"
            )
        except Exception as e:
            logger.error(f"AI command execution error: {e}")
            await ctx.reply("發生錯誤，請稍後再試")


async def setup(bot: Any) -> None:
    await bot.add_component(AIComponent(bot))
    logger.info("AI component loaded")


async def teardown(bot: Any) -> None:
    logger.info("AI component unloaded")
