import os
import logging
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, ChannelPrivateError, FloodWaitError
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import PeerChannel, PeerChat
import requests

# Токен вашего бота
TOKEN = '7833414798:AAFpEUyslDz0TrzWupNC2nrAk9gY2nFWzio'

# Укажите ваши данные для Telethon
api_id = '29758240'
api_hash = '45aa1a0337bf2ab7c931f4fa6a45b344'
phone_number = '+380958153249'  # Ваш номер телефона
session_file = 'user_session.session'  # Файл для сохранения сессии
output_folder = 'saved_posts'

# Файл для хранения ID каналов и групп
CHANNELS_FILE = 'channels.txt'
DONOR_CHANNELS_FILE = 'donor.txt'  # Файл с донорскими каналами и группами

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Хранилище состояния каналов и групп
channel_states = {}
selected_channels = {}
# Состояние ожидания ввода ID канала или группы для добавления
waiting_for_channel_id = {}
waiting_for_donor_channel_id = {}
# Флаг для остановки пересылки
stop_flag = {}

# Проверка соединения
def check_connection():
    try:
        requests.get("https://api.telegram.org", timeout=10)
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка соединения: {e}")
        return False
    return True

# Функция для отправки контента в канал или группу
async def send_content_to_channel(bot, channel_id, file):
    global stop_flag

    if stop_flag.get(channel_id, False):
        return

    file_path = os.path.join(output_folder, file)
    caption_file = None  # Инициализируем caption_file значением None по умолчанию
    try:
        if file.endswith('.txt'):
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
                await bot.send_message(chat_id=channel_id, text=text)
        elif file.endswith('.jpg') or file.endswith('.png'):
            caption_file = file_path.replace('.jpg', '_caption.txt').replace('.png', '_caption.txt')
            if os.path.exists(caption_file):
                with open(caption_file, 'r', encoding='utf-8') as f:
                    caption = f.read()
                    await bot.send_photo(chat_id=channel_id, photo=open(file_path, 'rb'), caption=caption)
            else:
                await bot.send_photo(chat_id=channel_id, photo=open(file_path, 'rb'))

        # Удаление файла после успешной отправки
        os.remove(file_path)
        if caption_file and os.path.exists(caption_file):
            os.remove(caption_file)

    except Exception as e:
        if "Flood control exceeded" in str(e):
            logger.error(f"Flood control error while sending message to channel or group {channel_id}: {e}")
            await asyncio.sleep(38)  # Wait for the specified time before retrying
        else:
            logger.error(f"Ошибка при отправке сообщения в канал или группу {channel_id}: {e}")

# Функция для выполнения копирования контента с донорского канала или группы
async def copy_content_from_donor(update: Update, context: ContextTypes.DEFAULT_TYPE, donor_channel_id):
    try:
        # Создание клиента
        client = TelegramClient(session_file, api_id, api_hash)

        # Авторизация
        try:
            await client.start(phone=phone_number)
        except SessionPasswordNeededError:
            await update.callback_query.answer("Нужно ввести двухфакторный пароль для аккаунта.", show_alert=True)
            await client.disconnect()
            return

        # Убедимся, что папка для сохранения существует
        os.makedirs(output_folder, exist_ok=True)

        logger.info(f"Читаем сообщения из канала или группы {donor_channel_id}")

        try:
            # Получаем канал или группу с помощью ID
            if donor_channel_id.startswith('-100'):
                peer = PeerChannel(int(donor_channel_id))
            else:
                peer = PeerChat(int(donor_channel_id))
            channel = await client.get_entity(peer)
        except ValueError as e:
            logger.error(f"Ошибка при копировании контента с канала или группы {donor_channel_id}: {e}")
            await update.callback_query.answer(f"Ошибка: {e}", show_alert=True)
            await client.disconnect()
            return
        except FloodWaitError as e:
            logger.error(f"Flood wait error: {e}")
            await update.callback_query.answer(f"Пожалуйста, подождите {e.seconds} секунд перед следующей попыткой.",
                                               show_alert=True)
            await client.disconnect()
            return

        # Проверим доступность канала или группы
        try:
            full_channel = await client(GetFullChannelRequest(channel=channel))
            logger.info(f"Канал или группа {donor_channel_id} доступен(а).")
        except ChannelPrivateError:
            await update.callback_query.answer(f"Канал или группа {donor_channel_id} приватный или недоступен.",
                                               show_alert=True)
            await client.disconnect()
            return

        # Получаем сообщения с канала или группы
        async for message in client.iter_messages(channel):
            # Сохранение текстовых сообщений
            if message.text:
                with open(os.path.join(output_folder, f"{message.id}.txt"), 'w', encoding='utf-8') as file:
                    file.write(message.text)

            # Сохранение медиа
            if message.media:
                # Скачиваем медиа
                file_path = await client.download_media(message, output_folder)
                logger.info(f"Медиа сохранено: {file_path}")

                # Если у медиа есть текст (подпись), сохраняем его в отдельный файл
                if message.text:
                    caption_path = os.path.splitext(file_path)[0] + '_caption.txt'
                    with open(caption_path, 'w', encoding='utf-8') as caption_file:
                        caption_file.write(message.text)

        await update.callback_query.answer("Контент успешно скопирован с канала или группы-донор.", show_alert=True)
        await client.disconnect()
    except ConnectionError as e:
        logger.error(f"Ошибка при копировании контента с канала или группы {donor_channel_id}: {e}")
        await update.callback_query.answer(f"Ошибка: {e}", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка при копировании контента с канала или группы {donor_channel_id}: {e}")
        await update.callback_query.answer(f"Ошибка: {e}", show_alert=True)

# Функция для копирования контента со всех донорских каналов и групп
async def copy_content_from_all_donors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(DONOR_CHANNELS_FILE):
        await update.callback_query.answer("Список донорских каналов и групп пуст.", show_alert=True)
        return

    with open(DONOR_CHANNELS_FILE, 'r') as f:
        donor_channel_ids = [line.strip() for line in f.readlines()]

    for donor_channel_id in donor_channel_ids:
        asyncio.create_task(copy_content_from_donor(update, context, donor_channel_id))

# Функция для отправки контента во все каналы и группы
async def send_content_to_all_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(CHANNELS_FILE):
        await update.callback_query.answer("Список каналов и групп пуст.", show_alert=True)
        return

    with open(CHANNELS_FILE, 'r') as f:
        channel_ids = [line.strip() for line in f.readlines()]

    files = sorted(os.listdir(output_folder), key=lambda x: os.path.getctime(os.path.join(output_folder, x)))
    for file in files:
        tasks = [send_content_to_channel(context.bot, channel_id, file) for channel_id in channel_ids]
        await asyncio.gather(*tasks)  # Параллельная отправка контента во все каналы и группы для одного файла

        # Удаление файла после успешной отправки во все каналы и группы
        file_path = os.path.join(output_folder, file)
        try:
            os.remove(file_path)
            caption_file = file_path.replace('.jpg', '_caption.txt').replace('.png', '_caption.txt')
            if os.path.exists(caption_file):
                os.remove(caption_file)
        except Exception as e:
            logger.error(f"Ошибка при удалении файла {file_path}: {e}")

# Функция для отправки контента в один канал или группу
async def send_content_to_single_channel(bot, channel_id):
    files = sorted(os.listdir(output_folder), key=lambda x: os.path.getctime(os.path.join(output_folder, x)))
    for file in files:
        await send_content_to_channel(bot, channel_id, file)
        await asyncio.sleep(0.2)  # Добавляем задержку в 0.2 секунды между отправками

# Функция для получения информации о канале или группе по их ID
async def get_channel_name(bot, channel_id):
    try:
        chat = await bot.get_chat(chat_id=channel_id)
        return chat.title  # Возвращаем название канала или группы
    except Exception as e:
        logger.error(f"Ошибка получения информации о канале или группе {channel_id}: {e}")
        return f"Неизвестный канал или группа ({channel_id})"

# Функция для добавления канала или группы
async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.callback_query.message.chat_id  # Получаем chat_id из callback_query
    waiting_for_channel_id[chat_id] = True
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Отправьте ID канала или группы, который вы хотите добавить.")

# Функция для добавления канала или группы-донор
async def add_donor_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.callback_query.message.chat_id  # Получаем chat_id из callback_query
    waiting_for_donor_channel_id[chat_id] = True
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "Отправьте ID донорского канала или группы, который вы хотите добавить.")

# Сохранение ID канала или группы
async def save_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channel_id = update.message.text.strip()

    chat_id = update.message.chat_id
    if waiting_for_channel_id.get(chat_id, False):
        if not channel_id.isdigit() and not channel_id.startswith('-100') and not channel_id.startswith('-'):
            await update.message.reply_text("Неверный формат ID канала или группы. Попробуйте ещё раз.")
            return

        with open(CHANNELS_FILE, 'a') as f:
            f.write(f"{channel_id}\n")

        channel_states[channel_id] = False

        waiting_for_channel_id[chat_id] = False

        await update.message.reply_text(f"Канал или группа с ID {channel_id} добавлен(а).")
    elif waiting_for_donor_channel_id.get(chat_id, False):
        if not channel_id.isdigit() and not channel_id.startswith('-100') and not channel_id.startswith('-'):
            await update.message.reply_text("Неверный формат ID канала или группы. Попробуйте ещё раз.")
            return

        with open(DONOR_CHANNELS_FILE, 'a') as f:
            f.write(f"{channel_id}\n")

        waiting_for_donor_channel_id[chat_id] = False

        await update.message.reply_text(f"Донорский канал или группа с ID {channel_id} добавлен(а).")
    else:
        await update.message.reply_text("Вы не нажали кнопку для добавления канала или группы.")

# Функция для отображения списка каналов и групп
async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot

    if not os.path.exists(CHANNELS_FILE):
        await update.callback_query.answer("Список каналов и групп пуст.", show_alert=True)
        return

    with open(CHANNELS_FILE, 'r') as f:
        channel_ids = [line.strip() for line in f.readlines()]

    if not channel_ids:
        await update.callback_query.answer("Список каналов и групп пуст.", show_alert=True)
        return

    keyboard = []
    for channel_id in channel_ids:
        channel_name = await get_channel_name(bot, channel_id)
        keyboard.append([InlineKeyboardButton(channel_name, callback_data=f"channel_{channel_id}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.message.reply_text("Список каналов и групп:", reply_markup=reply_markup)

# Функция для отображения списка донорских каналов и групп
async def list_donor_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot

    if not os.path.exists(DONOR_CHANNELS_FILE):
        await update.callback_query.answer("Список донорских каналов и групп пуст.", show_alert=True)
        return

    with open(DONOR_CHANNELS_FILE, 'r') as f:
        donor_channel_ids = [line.strip() for line in f.readlines()]

    if not donor_channel_ids:
        await update.callback_query.answer("Список донорских каналов и групп пуст.", show_alert=True)
        return

    keyboard = []
    for channel_id in donor_channel_ids:
        channel_name = await get_channel_name(bot, channel_id)
        keyboard.append([InlineKeyboardButton(channel_name, callback_data=f"donor_{channel_id}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.message.reply_text("Список донорских каналов и групп:", reply_markup=reply_markup)

# Обработчик нажатий на кнопки
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global stop_flag

    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id

    if query.data.startswith('channel_'):
        channel_id = query.data.split('_')[1]
        keyboard = [
            [InlineKeyboardButton("Start", callback_data=f"start_channel_{channel_id}")],
            [InlineKeyboardButton("Stop", callback_data=f"stop_channel_{channel_id}")],
            [InlineKeyboardButton("Full Start", callback_data=f"full_start_channel_{channel_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(f"Управление каналом или группой {channel_id}:", reply_markup=reply_markup)

    elif query.data.startswith('donor_'):
        donor_channel_id = query.data.split('_')[1]
        keyboard = [
            [InlineKeyboardButton("Start", callback_data=f"start_donor_{donor_channel_id}")],
            [InlineKeyboardButton("Stop", callback_data=f"stop_donor_{donor_channel_id}")],
            [InlineKeyboardButton("Full Start", callback_data=f"full_start_donor_{donor_channel_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(f"Управление донорским каналом или группой {donor_channel_id}:",
                                       reply_markup=reply_markup)

    elif query.data.startswith('start_channel_'):
        channel_id = query.data.split('_')[2]
        stop_flag[channel_id] = False
        asyncio.create_task(send_content_to_single_channel(context.bot, channel_id))

    elif query.data.startswith('stop_channel_'):
        channel_id = query.data.split('_')[2]
        stop_flag[channel_id] = True

    elif query.data.startswith('full_start_channel_'):
        channel_id = query.data.split('_')[2]
        stop_flag[channel_id] = False
        asyncio.create_task(send_content_to_single_channel(context.bot, channel_id))

    elif query.data.startswith('start_donor_'):
        donor_channel_id = query.data.split('_')[2]

        # Передаем ID канала или группы-донор в функцию копирования контента
        with open(DONOR_CHANNELS_FILE, 'r') as f:
            donor_channel_ids = [line.strip() for line in f.readlines()]

        if donor_channel_id in donor_channel_ids:
            asyncio.create_task(copy_content_from_donor(update, context, donor_channel_id=donor_channel_id))

    elif query.data.startswith('stop_donor_'):
        donor_channel_id = query.data.split('_')[2]
        stop_flag[donor_channel_id] = True

    elif query.data.startswith('full_start_donor_'):
        donor_channel_id = query.data.split('_')[2]
        stop_flag[donor_channel_id] = False
        asyncio.create_task(copy_content_from_donor(update, context, donor_channel_id=donor_channel_id))

    elif query.data == 'copy_content':
        asyncio.create_task(copy_content_from_all_donors(update, context))

    elif query.data == 'send_content':
        asyncio.create_task(send_content_to_all_channels(update, context))

    elif query.data == 'add_channel':
        await add_channel(update, context)
    elif query.data == 'add_donor_channel':
        await add_donor_channel(update, context)
    elif query.data == 'list_channels':
        await list_channels(update, context)
    elif query.data == 'list_donor_channels':
        await list_donor_channels(update, context)

# Обновление стартового меню
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Скопировать со всех каналов и групп", callback_data='copy_content')],
        [InlineKeyboardButton("Отправить во все каналы и группы", callback_data='send_content')],
        [InlineKeyboardButton("Добавить канал или группу", callback_data='add_channel')],
        [InlineKeyboardButton("Добавить канал или группу-донор", callback_data='add_donor_channel')],
        [InlineKeyboardButton("Список каналов и групп", callback_data='list_channels')],
        [InlineKeyboardButton("Каналы и группы доноры", callback_data='list_donor_channels')],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Выберите действие:', reply_markup=reply_markup)
# Основная функция
async def main():
    # Создаем экземпляр приложения
    application = Application.builder().token(TOKEN).build()

    # Добавляем обработчики команд и сообщений
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_channel))

    # Запускаем приложение в асинхронном режиме
    await application.initialize()
    await application.start()
    logger.info("Bot started")

    # Создаем задачу для завершения приложения
    await application.updater.start_polling()
    await application.idle()


# Проверка соединения
def check_connection():
    try:
        requests.get("https://api.telegram.org", timeout=10)
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка соединения: {e}")
        return False
    return True


# Запуск основной функции
if __name__ == '__main__':
    if check_connection():
        asyncio.run(main())
    else:
        logger.error("Нет соединения с Telegram API")