import logging
import random
from datetime import datetime
from typing import Any

from twitchio.ext import commands

logger = logging.getLogger(__name__)


class FortuneComponent(commands.Component):  # type: ignore[misc]
    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self._init_fortune_data()
        logger.info("Fortune component initialized")

    def _init_fortune_data(self) -> None:
        """初始化運勢數據"""
        # 運勢等級與權重
        self.fortune_levels = {
            "大吉": (10, "🌟 超級幸運！時來運轉，萬事亨通！"),
            "中吉": (15, "✨ 運氣不錯！好事近在眼前"),
            "小吉": (20, "⭐ 運勢平穩，積極努力就有好結果"),
            "平": (35, "🌙 平平安安，順順利利"),
            "末吉": (10, "☁️ 稍有阻礙，但無大礙"),
            "凶": (7, "⚡ 小心謹慎，逢凶化吉"),
            "大凶": (3, "☔ 諸事不宜，需要避禍趨吉"),
        }

        # 特殊日期運勢加成
        self.special_dates = {
            (1, 1): ("新年大吉", 1.3),
            (2, 14): ("情人節", 1.2),
            (12, 25): ("聖誕節", 1.1),
            (10, 31): ("萬聖節", 0.9),
        }

        # 運勢內容池
        self.fortune_pool = {
            "好": {
                "事業": [
                    "貴人相助，事業蒸蒸日上 BloodTrail",
                    "升職加薪的機會來了 BloodTrail",
                    "工作表現被肯定，好評不斷 BloodTrail",
                    "新的發展機會即將出現 BloodTrail",
                ],
                "財運": [
                    "橫財即將入袋 💰",
                    "投資有意外收穫 💰",
                    "財運亨通，適合投資 💰",
                    "偏財運旺盛 💰",
                ],
                "愛情": [
                    "桃花朵朵開，良緣將至 💕",
                    "感情甜蜜，充滿驚喜 💕",
                    "適合告白或推進關係 💕",
                    "戀愛運勢大爆發 💕",
                ],
                "健康": [
                    "精神飽滿，活力充沛 💪",
                    "身體健康，免疫力強 💪",
                    "適合開始新運動計畫 💪",
                    "心情愉悅，壓力全消 💪",
                ],
            },
            "中": {
                "事業": [
                    "工作穩定發展中 SeemsGood",
                    "保持現狀繼續努力 SeemsGood",
                    "多關注工作細節 SeemsGood",
                    "適合進修充電 SeemsGood",
                ],
                "財運": [
                    "財運平穩，適合儲蓄",
                    "量入為出，可小額投資",
                    "理財要保守為上",
                    "正財運佳",
                ],
                "愛情": [
                    "感情穩定發展中",
                    "多些浪漫小驚喜",
                    "關係需要用心經營",
                    "保持良好溝通很重要",
                ],
                "健康": [
                    "身體狀況穩定",
                    "注意作息規律",
                    "適度運動有益健康",
                    "保持良好心態",
                ],
            },
            "差": {
                "事業": [
                    "工作上需要特別謹慎 ResidentSleeper",
                    "暫時不適合重大決定 ResidentSleeper",
                    "需要調整工作方向 ResidentSleeper",
                    "避免與人發生爭執 ResidentSleeper",
                ],
                "財運": [
                    "避免衝動消費",
                    "理財要特別謹慎",
                    "暫時不宜大筆投資",
                    "小心錢財損失",
                ],
                "愛情": [
                    "感情需要多些耐心",
                    "避免爭執與誤會",
                    "感情事多加考慮",
                    "先專注自我提升",
                ],
                "健康": [
                    "多注意身體狀況",
                    "避免熬夜過勞",
                    "飲食要特別注意",
                    "減少壓力來源",
                ],
            },
        }

        # 宜忌建議池
        self.advice_pool = {
            "宜": {
                "好": [
                    "投資理財",
                    "做重大決定",
                    "開始新計畫",
                    "學習新技能",
                    "聯絡朋友",
                    "運動健身",
                    "勇敢告白",
                    "安排旅遊",
                ],
                "中": [
                    "整理環境",
                    "規劃未來",
                    "閱讀書籍",
                    "聽音樂",
                    "散步放鬆",
                    "溫習功課",
                    "烹飪料理",
                    "看電影",
                    "聊天社交",
                ],
                "差": [
                    "休息養神",
                    "沉澱思考",
                    "保守理財",
                    "多喝水",
                    "早睡早起",
                    "靜心冥想",
                    "整理房間",
                    "清理檔案",
                    "陪伴家人",
                ],
            },
            "忌": {
                "好": [
                    "過度樂觀",
                    "衝動決定",
                    "炫耀成就",
                    "忽視細節",
                    "過度消費",
                    "輕信他人",
                    "急躁行事",
                    "驕傲自滿",
                ],
                "中": [
                    "熬夜",
                    "暴飲暴食",
                    "拖延重要事項",
                    "情緒化購物",
                    "長時間久坐",
                    "過度使用電子產品",
                    "忽視溝通",
                    "固執己見",
                ],
                "差": [
                    "情緒化決定",
                    "與人爭執",
                    "熬夜工作",
                    "變更重要計畫",
                    "缺乏運動",
                    "忽略家人",
                ],
            },
        }

        # 幸運元素
        self.lucky_elements = {
            "好": {
                "colors": ["紅色", "金色", "紫色", "粉色"],
                "numbers": list(range(1, 10)),
                "hours": ["午時 11:00-13:00", "子時 23:00-01:00", "卯時 05:00-07:00"],
            },
            "中": {
                "colors": ["藍色", "綠色", "白色", "黃色"],
                "numbers": list(range(11, 50)),
                "hours": ["巳時 09:00-11:00", "申時 15:00-17:00", "酉時 17:00-19:00"],
            },
            "差": {
                "colors": ["黑色", "灰色", "棕色", "深藍"],
                "numbers": list(range(51, 100)),
                "hours": ["寅時 03:00-05:00", "戌時 19:00-21:00", "亥時 21:00-23:00"],
            },
        }

        # 運勢分類映射
        self.category_map = {
            "大吉": "好",
            "中吉": "好",
            "小吉": "中",
            "平": "中",
            "末吉": "差",
            "凶": "差",
            "大凶": "差",
        }

        # 預計算權重列表
        self.levels_list = list(self.fortune_levels.keys())
        self.weights_list = [
            self.fortune_levels[level][0] for level in self.levels_list
        ]

    def _get_fortune_level(self, date_modifier: float = 1.0) -> str:
        """根據權重隨機選擇運勢等級"""
        if date_modifier != 1.0:
            weights = [w * date_modifier for w in self.weights_list]
        else:
            weights = self.weights_list  # type: ignore[assignment]
        return random.choices(self.levels_list, weights=weights, k=1)[0]

    def _get_date_bonus(self) -> tuple[str | None, float]:
        """檢查今日特殊日期加成"""
        today = datetime.now()
        date_key = (today.month, today.day)
        if date_key in self.special_dates:
            return self.special_dates[date_key]
        return None, 1.0

    def _generate_fortune_details(self, category: str) -> dict[str, str]:
        """生成運勢詳情"""
        pool = self.fortune_pool[category]
        # 每個類別都選一個
        return {f"{type_}": random.choice(messages) for type_, messages in pool.items()}

    def _generate_daily_advice(self, category: str) -> tuple[list[str], list[str]]:
        """生成今日宜忌"""
        # 宜：從對應category抽取1個
        good_advice = random.sample(self.advice_pool["宜"][category], 1)

        # 忌：從對應category抽取1個
        avoid_advice = random.sample(self.advice_pool["忌"][category], 1)

        return good_advice, avoid_advice

    def _get_lucky_elements(self, category: str) -> tuple[str, int, str]:
        """獲取幸運元素"""
        elements = self.lucky_elements[category]
        return (
            random.choice(elements["colors"]),  # type: ignore[arg-type]
            random.choice(elements["numbers"]),  # type: ignore[arg-type]
            random.choice(elements["hours"]),  # type: ignore[arg-type]
        )

    def _build_message(
        self,
        user: str,
        fortune_level: str,
        description: str,
        special_event: str | None,
        detailed_fortunes: dict[str, str],
        good_advice: list[str],
        avoid_advice: list[str],
        lucky_color: str,
        lucky_number: int,
        lucky_hour: str,
    ) -> str:
        """構建運勢訊息"""
        parts = [f"🔮 {user} 的今日運勢"]
        parts.append(f"總運勢：{fortune_level} {description}")

        if special_event:
            parts.append(f"今日是{special_event}，運勢有額外加成！")

        for category, detail in detailed_fortunes.items():
            parts.append(f"{category}：{detail}")

        parts.extend(
            [
                f"幸運色：{lucky_color}",
                f"幸運數字：{lucky_number}",
                f"最佳時機：{lucky_hour}",
                f"宜：{' 、 '.join(good_advice)}",
                f"忌：{' 、 '.join(avoid_advice)}",
            ]
        )

        return " | ".join(parts)

    # type: ignore[misc]
    @commands.command(name="運勢", aliases=["fortune", "占卜"])
    # type: ignore[misc]
    @commands.cooldown(rate=1, per=30, key=commands.BucketType.chatter)
    async def fortune_command(self, ctx: Any) -> None:
        """運勢占卜指令"""
        user = ctx.chatter.display_name or ctx.chatter.name

        try:
            # 檢查特殊日期加成
            special_event, date_modifier = self._get_date_bonus()

            # 抽取運勢
            fortune_level = self._get_fortune_level(date_modifier)
            category = self.category_map[fortune_level]
            description = self.fortune_levels[fortune_level][1]

            # 生成詳細內容
            detailed_fortunes = self._generate_fortune_details(category)
            good_advice, avoid_advice = self._generate_daily_advice(category)
            lucky_color, lucky_number, lucky_hour = self._get_lucky_elements(category)

            # 構建並發送訊息
            message = self._build_message(
                user,
                fortune_level,
                description,
                special_event,
                detailed_fortunes,
                good_advice,
                avoid_advice,
                lucky_color,
                lucky_number,
                lucky_hour,
            )

            await ctx.reply(message)
            logger.debug(f"User {user} fortune reading: {fortune_level}")

        except Exception as e:
            logger.error(f"Fortune reading error: {e}")
            await ctx.reply("占卜過程中發生神秘干擾，請稍後再試 BloodTrail")


async def setup(bot: Any) -> None:
    await bot.add_component(FortuneComponent(bot))
    logger.info("Fortune component loaded")


async def teardown(bot: Any) -> None:
    logger.info("Fortune component unloaded")
