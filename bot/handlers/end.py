import json

from aiogram import types, F
from aiogram.filters import Command

from config import ADMIN_IDS
from loader import dp, bot


@dp.message(Command("get_photo_id"), F.content_type == "photo")
async def get_photo_id(message: types.Message):
    photos = message.photo
    largest_photo = max(photos, key=lambda p: p.file_size)
    await message.reply(
        f"📸 <b>Photo ID:</b>\n<code>{largest_photo.file_id}</code>", parse_mode="HTML"
    )


@dp.message(Command("raw"))
async def get_message_json(message: types.Message):
    message_json = message.model_dump(exclude_defaults=True, exclude_none=True)
    formatted_json = json.dumps(message_json, indent=2, ensure_ascii=False)
    if len(formatted_json) > 3900:
        formatted_json = formatted_json[:3900] + "\n... (обрезано)"
    await message.reply(
        f"📄 *Raw JSON содержимого сообщения:*\n```json\n{formatted_json}```",
        parse_mode="Markdown",
    )


@dp.message()
async def unexpected_message(message: types.Message):
    if message.from_user.is_bot is False:
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=f"{message.from_user.id} - {message.from_user.username}:",
                )
                await message.forward(chat_id=admin_id)
            except Exception:
                pass
