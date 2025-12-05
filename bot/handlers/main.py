from datetime import datetime

from aiogram import types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext

from loader import dp
from view import messages


@dp.message(CommandStart())
async def start(message: types.Message, state: FSMContext):
    await state.set_state(None)
    data = await state.get_data()

    if "start_text" not in data:
        start_text = message.text[7:]
        await state.update_data(
            start_timestamp=datetime.now().isoformat(),
            start_text=start_text,
            chat_id=message.from_user.id,
            username=message.from_user.username,
        )

    await message.answer(text=messages.start)
