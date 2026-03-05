import os
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# -------------------- Загрузка настроек --------------------
load_dotenv(".env")
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
OWNER_ID = os.getenv("OWNER_ID")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# -------------------- База данных --------------------
Base = declarative_base()
engine = create_engine("sqlite:///bot_db.sqlite")
Session = sessionmaker(bind=engine)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True)
    display_name = Column(String)
    blocked = Column(Boolean, default=False)

class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    display_name = Column(String)
    status = Column(String, default="open")  # open / in_progress / closed
    admin = Column(String, nullable=True)
    thread_id = Column(Integer, nullable=True)  # id темы в Telegram

Base.metadata.create_all(engine)

# -------------------- Кнопки для админов --------------------
def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("Взять в работу", callback_data="take")],
        [InlineKeyboardButton("Отказаться", callback_data="decline")],
        [InlineKeyboardButton("Закрыть диалог", callback_data="close")],
        [InlineKeyboardButton("Передать другому админу", callback_data="transfer")]
    ])

# -------------------- /start --------------------
@dp.message(CommandStart())
async def start_bot(message: Message):
    session = Session()
    user = session.query(User).filter_by(telegram_id=message.from_user.id).first()
    if user:
        await message.answer("Вы уже начали диалог ранее.")
        session.close()
        return
    await message.answer(
        "Привет! Придумай, пожалуйста, псевдоним, под которым тебя будут видеть админы.\n"
        "Если хочешь пропустить — мы создадим его автоматически."
    )
    session.close()

# -------------------- Псевдоним --------------------
@dp.message(F.text)
async def handle_nickname(message: Message):
    session = Session()
    user = session.query(User).filter_by(telegram_id=message.from_user.id).first()
    if user:
        # Уже есть пользователь, отправляем его сообщение в тикет
        ticket = session.query(Ticket).filter_by(user_id=user.id, status!="closed").first()
        if ticket:
            if message.reply_to_message:  # игнорируем, если это reply
                session.close()
                return
            # пересылаем в админ-группу (тема)
            await bot.send_message(ticket.thread_id or ADMIN_CHAT_ID,
                                   f"{message.text}")
        session.close()
        return

    # Новый пользователь → создаём псевдоним и тикет
    display_name = message.text.strip() or f"User{message.from_user.id}"
    new_user = User(telegram_id=message.from_user.id, display_name=display_name)
    session.add(new_user)
    session.commit()

    # Создание тикета (тема в админ-группе)
    # Для демонстрации используем обычный чат (api create forum topic в aiogram 3.3)
    # TODO: если будет подключён реальный суперчат, здесь нужно создать тему
    new_ticket = Ticket(user_id=new_user.id, display_name=display_name, status="open")
    session.add(new_ticket)
    session.commit()
    session.close()

    await message.answer("Спасибо! Теперь мы не потеряем твои сообщения. Админ скоро ответит.")
    await bot.send_message(ADMIN_CHAT_ID,
                           f"Новый тикет #{new_ticket.id} | {display_name}",
                           reply_markup=admin_keyboard())

# -------------------- Callback для админов --------------------
@dp.callback_query()
async def admin_actions(callback: CallbackQuery):
    session = Session()
    data = callback.data
    # Определяем тикет
    ticket_id = int(callback.message.text.split("#")[1].split()[0])
    ticket = session.query(Ticket).filter_by(id=ticket_id).first()
    if not ticket:
        await callback.answer("Тикет не найден")
        session.close()
        return

    if data == "take":
        ticket.admin = callback.from_user.username
        ticket.status = "in_progress"
        await callback.message.edit_text(f"#{ticket.id} | {ticket.display_name} | @{ticket.admin}")
        await callback.message.answer(f"Ответственный: @{ticket.admin}")
        await callback.answer("Вы взяли тикет в работу")
    elif data == "decline":
        ticket.admin = None
        ticket.status = "open"
        await callback.answer("Вы отказались от тикета")
    elif data == "close":
        ticket.status = "closed"
        await callback.message.edit_text(f"#{ticket.id} | {ticket.display_name} | закрыт")
        await bot.send_message(ticket.user_id, "Диалог завершён.")
        await callback.answer("Тикет закрыт")
    elif data == "transfer":
        ticket.admin = None
        ticket.status = "open"
        await callback.message.answer("Тикет доступен для другого администратора")
        await callback.answer("Тикет передан другому админу")
    session.commit()
    session.close()

# -------------------- Запуск --------------------
if __name__ == "__main__":
    import asyncio
    asyncio.run(dp.start_polling(bot))