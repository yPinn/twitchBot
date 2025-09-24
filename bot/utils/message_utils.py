from typing import Any


def is_self_message(bot: Any, message: Any) -> bool:
    # 優先用 echo（IRC echo extension）
    if getattr(message, "echo", False):
        return True

    # 比對 bot.user 物件
    if (
        getattr(bot, "user", None) is not None
        and getattr(message, "chatter", None) == bot.user
    ):
        return True

    # 最後比對 user_id
    if getattr(message.chatter, "id", None) and getattr(bot, "user_id", None):
        return message.chatter.id == bot.user_id

    return False
