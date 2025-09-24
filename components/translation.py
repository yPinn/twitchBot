import logging
import re
import time
from typing import Any

import twitchio
from googletrans import Translator
from twitchio.ext import commands

from utils.message_utils import is_self_message

logger = logging.getLogger(__name__)


class TranslationComponent(commands.Component):  # type: ignore[misc]
    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self.user_cooldowns: dict[str, float] = {}
        self.cooldown_seconds = 5

        # 預編譯正則表達式
        self.chinese_pattern = re.compile(r"[\u4e00-\u9fff]")
        self.english_pattern = re.compile(r"^[a-zA-Z\s\.\,\!\?\'\"\-\(\)0-9]+$")
        self.meaningless_patterns = [
            re.compile(r"^(.)\1{2,}$"),
            re.compile(r"^[a-z]{1,2}$"),
            re.compile(r"^\d+$"),
            re.compile(r"^(ha|he|ho|hi|la|na|ma|da){2,}$"),
        ]

        # 常見表情符號
        self.common_emotes = {
            "LUL",
            "LULW",
            "KEKW",
            "OMEGALUL",
            "PogChamp",
            "Kappa",
            "MonkaS",
            "WeirdChamp",
            "EZClap",
        }
        self.common_short_words = {"u", "ur", "r", "ok", "ty", "np", "hi", "yo", "no"}

        logger.info("Translation component initialized")

    def _extract_text_from_message(self, payload: Any) -> str | None:
        """從訊息中提取純文字內容，排除表情符號"""
        words = payload.text.split()
        text_words = [word for word in words if not self._is_likely_emote(word)]
        return " ".join(text_words).strip() if text_words else None

    def _is_likely_emote(self, word: str) -> bool:
        """判斷詞彙是否可能是表情符號"""
        word_len = len(word)
        if word_len < 2 or word_len > 25 or not word.isalnum():
            return False

        # 檢查預定義表情符號
        if word in self.common_emotes:
            return True

        # 英文加數字組合 (如 Roger888888)
        if any(c.isalpha() for c in word) and any(c.isdigit() for c in word):
            return True

        # 大小寫混合模式
        if (
            word != word.lower()
            and word != word.upper()
            and any(c.isupper() for c in word)
            and any(c.islower() for c in word)
        ):
            return True

        # 全大寫短詞
        return word.isupper() and 3 <= word_len <= 8

    def _is_meaningless_translation(self, original: str, translated: str) -> bool:
        """檢查翻譯結果是否無意義"""
        if not original or not translated:
            return False

        # 只有大小寫差別
        if original.lower() == translated.lower():
            return True

        # 完全相同
        if original == translated:
            return True

        # 高相似度檢查
        if len(original) == len(translated) and len(original) > 6:
            similar_chars = sum(
                1
                for a, b in zip(original.lower(), translated.lower(), strict=False)
                if a == b
            )
            return (similar_chars / len(original)) > 0.8

        return False

    def _is_meaningful_content(self, text: str) -> bool:
        clean_text = text.lower()

        for pattern in self.meaningless_patterns:
            if pattern.match(clean_text):
                return False

        if len(text.split()) == 1:
            return len(clean_text) >= 3 or clean_text in self.common_short_words

        return True

    def should_translate(self, text: str, payload: Any = None) -> bool:
        clean_text = text.strip()

        # 快速過濾
        if (
            len(clean_text) < 2
            or clean_text.startswith(("!", "@"))
            or self.chinese_pattern.search(clean_text)
            or not any(c.isalpha() for c in clean_text)
        ):
            return False

        # 單詞檢查：如果只有一個詞且包含英文+數字組合，不翻譯
        words = clean_text.split()
        if len(words) == 1:
            word = words[0]
            if any(c.isalpha() for c in word) and any(c.isdigit() for c in word):
                return False

        # 有表情符號的處理
        if payload and payload.emotes:
            extracted_text = self._extract_text_from_message(payload)
            if extracted_text and len(extracted_text) >= 2:
                return bool(
                    self.english_pattern.match(extracted_text)
                    and self._is_meaningful_content(extracted_text)
                )
            return False

        # 無表情符號的普通檢查
        return bool(
            self.english_pattern.match(clean_text)
            and self._is_meaningful_content(clean_text)
        )

    def check_cooldown(self, user_id: str) -> bool:
        now = time.time()
        if (
            user_id in self.user_cooldowns
            and now - self.user_cooldowns[user_id] < self.cooldown_seconds
        ):
            return True
        self.user_cooldowns[user_id] = now
        return False

    async def translate_text(self, text: str, target: str = "zh-tw") -> str | None:
        try:
            async with Translator() as translator:
                result = await translator.translate(text, src="en", dest=target)
                return result.text  # type: ignore[no-any-return]
        except Exception as e:
            logger.error(f"Translation failed: {e}")
            return None

    @commands.Component.listener()  # type: ignore[misc]
    async def event_message(self, payload: twitchio.ChatMessage) -> None:
        try:
            if is_self_message(self.bot, payload) or any(
                prefix in payload.text for prefix in ["[英文]", "→"]
            ):
                return

            content = payload.text.strip()
            if not self.should_translate(content, payload) or self.check_cooldown(
                payload.chatter.id
            ):
                return

            # 決定翻譯內容
            if payload.emotes:
                text_to_translate = self._extract_text_from_message(payload)
                if not text_to_translate:
                    return
            else:
                text_to_translate = content

            translated = await self.translate_text(text_to_translate)
            if not translated or translated == text_to_translate:
                return

            # 檢查翻譯結果是否無意義
            if self._is_meaningless_translation(text_to_translate, translated):
                return

            final_response = f"[英文] {translated}"

            # 發送回覆
            try:
                original_text = payload.text
                payload.text = "!_translate_reply"
                ctx = self.bot.get_context(payload)
                payload.text = original_text

                if ctx and hasattr(ctx, "reply"):
                    await ctx.reply(final_response)
                    logger.debug(
                        f"Auto-translate [{payload.broadcaster.name}] {payload.chatter.name}: {text_to_translate[:30]}... -> {translated[:30]}..."
                    )
                else:
                    await self._fallback_mention(payload, final_response)

            except Exception as e:
                logger.error(f"Context hack failed: {e}")
                await self._fallback_mention(payload, final_response)

        except Exception as e:
            logger.error(f"Auto-translation error: {e}")

    async def _fallback_mention(
        self, payload: twitchio.ChatMessage, response_text: str
    ) -> None:
        clean_response = (
            response_text.replace("[英文] ", "")
            if response_text.startswith("[英文] ")
            else response_text
        )
        message = f"@{payload.chatter.name} [英文] {clean_response}"
        await payload.broadcaster.send_message(sender=self.bot.bot_id, message=message)
        logger.debug(
            f"Auto-translate fallback [{payload.broadcaster.name}] {payload.chatter.name}: {clean_response[:30]}..."
        )

    # type: ignore[misc]
    @commands.command(name="_translate_reply", hidden=True)
    async def translate_reply_dummy(self, ctx: commands.Context) -> None:
        pass

    # type: ignore[misc]
    @commands.command(name="翻譯", aliases=["translate", "tr"])
    async def translate_command(
        self, ctx: commands.Context, *, text: str | None = None
    ) -> None:
        if not text:
            await ctx.reply("用法: !翻譯 <英文文字>")
            return

        translated = await self.translate_text(text)
        if translated:
            # 檢查翻譯結果是否無意義
            if self._is_meaningless_translation(text, translated):
                await ctx.reply(f"'{text}' 可能是專有名詞或表情符號，無法翻譯")
                return

            await ctx.reply(f"[英文] {translated}")
            logger.debug(
                f"Manual translate [{ctx.broadcaster.name}] {ctx.chatter.name}: {text[:20]}... -> {translated[:20]}..."
            )
        else:
            await ctx.reply("翻譯失敗，請稍後再試")


async def setup(bot: Any) -> None:
    component = TranslationComponent(bot)
    await bot.add_component(component)
    logger.info("Translation component loaded")


async def teardown(bot: Any) -> None:
    logger.info("Translation component unloaded")
