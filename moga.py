import logging
import asyncio
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, ConversationHandler
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from telethon.tl.types import Channel, Chat

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ТВОЙ ТОКЕН БОТА
BOT_TOKEN = "8595350890:AAErzOWwSXRNzDlTsUlBHbk9CB-rq7L5ryE"

# ТВОИ API ДАННЫЕ
API_ID = 37603888
API_HASH = "3d372f640db5b42081df67f6566b777d"

# Состояния для авторизации
PHONE, CODE, PASSWORD = range(3)

# Состояния для рассылки
MODE, RECIPIENTS, MESSAGE_TEXT, CYCLES, INTERVAL, CONFIRM = range(6)

# Хранилище сессий и активных рассылок
user_sessions = {}
active_broadcasts = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = """
🤖 Добро пожаловать в Moga Рассылку!

Доступные команды:
/auth - Авторизация в Telegram  
/broadcast - Начать массовую рассылку
/stop_broadcast - Остановить рассылку
/my_broadcasts - Мои активные рассылки
/status - Статус подключения
/help - Помощь и инструкции

Поддержка: @mirnibro9i
Внимание: Соблюдайте правила Telegram!
    """
    await update.message.reply_text(welcome_text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📖 Помощь по боту:

1. Сначала авторизуйтесь через /auth
2. Затем настройте рассылку через /broadcast  
3. Следуйте инструкций бота

ВАЖНО: Бот не несет ответственность за блокировки!
    """
    await update.message.reply_text(help_text)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_sessions:
        status_text = "🟢 Статус: Авторизован"
    else:
        status_text = "🔴 Статус: Не авторизован\nИспользуйте /auth для авторизации"
    await update.message.reply_text(status_text)

# ========== СИСТЕМА АВТОРИЗАЦИИ ==========

async def auth_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало авторизации - запрос номера телефона"""
    auth_text = """
АВТОРИЗАЦИЯ В TELEGRAM

Введите ваш номер телефона в международном формате:
Пример: +79123456789

Важно: Используйте номер, привязанный к Telegram
    """
    await update.message.reply_text(auth_text)
    return PHONE

async def auth_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка номера телефона"""
    phone_number = update.message.text
    context.user_data['phone'] = phone_number
    
    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()
        
        sent_code = await client.send_code_request(phone_number)
        context.user_data['client'] = client
        context.user_data['phone_code_hash'] = sent_code.phone_code_hash
        
        await update.message.reply_text("✅ Код отправлен! Введите код из Telegram:")
        return CODE
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}\nПопробуйте снова /auth")
        return ConversationHandler.END

async def auth_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кода подтверждения"""
    code = update.message.text
    client = context.user_data['client']
    phone = context.user_data['phone']
    phone_code_hash = context.user_data['phone_code_hash']
    
    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        
        session_string = client.session.save()
        user_id = update.effective_user.id
        user_sessions[user_id] = session_string
        
        await update.message.reply_text("✅ Авторизация успешна! Теперь можете использовать /broadcast")
        await client.disconnect()
        return ConversationHandler.END
        
    except SessionPasswordNeededError:
        await update.message.reply_text("🔐 Включена двухэтапная аутентификация.Введите ваш пароль:")
        return PASSWORD
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка авторизации: {e}\nПопробуйте снова /auth")
        await client.disconnect()
        return ConversationHandler.END

async def auth_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка пароля двухэтапной аутентификации"""
    password = update.message.text
    client = context.user_data['client']
    
    try:
        await client.sign_in(password=password)
        
        session_string = client.session.save()
        user_id = update.effective_user.id
        user_sessions[user_id] = session_string
        
        await update.message.reply_text("✅ Авторизация успешна! Теперь можете использовать /broadcast")
        await client.disconnect()
        return ConversationHandler.END
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка входа с паролем: {e}\nПопробуйте снова /auth")
        await client.disconnect()
        return ConversationHandler.END

async def auth_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена авторизации"""
    await update.message.reply_text("Авторизация отменена.")
    return ConversationHandler.END

# ========== СИСТЕМА РАССЫЛКИ С АВТОПОИСКОМ ==========

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало настройки рассылки"""
    user_id = update.effective_user.id
    if user_id not in user_sessions:
        await update.message.reply_text("❌ Сначала авторизуйтесь через /auth")
        return ConversationHandler.END
    
    mode_text = """
🔍 ВЫБЕРИТЕ РЕЖИМ РАССЫЛКИ:

1️⃣ РУЧНОЙ ВВОД - введите получателей через запятую
2️⃣ АВТОПОИСК - бот найдет все чаты с 1000+ участниками

Введите 1 или 2:
    """
    await update.message.reply_text(mode_text)
    return MODE

async def broadcast_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора режима"""
    mode = update.message.text.strip()
    
    if mode == "1":
        # Ручной ввод
        recipients_text = """
НАСТРОЙКА ПОЛУЧАТЕЛЕЙ

Введите получателей (через запятую):
- @username
- ID пользователя/чата  
- Ссылки на чаты

Пример: @user1, 123456789, @user2, -1001234567890

Примечание: ID чатов обычно начинаются с -100
        """
        await update.message.reply_text(recipients_text)
        return RECIPIENTS
        
    elif mode == "2":
        # Автопоиск чатов
        await update.message.reply_text("🔍 Ищу чаты с 1000+ участниками...")
        
        try:
            # Подключаемся к аккаунту
            client = TelegramClient(StringSession(user_sessions[update.effective_user.id]), API_ID, API_HASH)
            await client.connect()
            
            # Получаем все диалоги
            dialogs = await client.get_dialogs()
            large_chats = []
            
            for dialog in dialogs:
                if dialog.is_channel or dialog.is_group:
                    try:
                        entity = dialog.entity
                        if hasattr(entity, 'participants_count') and entity.participants_count >= 1000:
                            if hasattr(entity, 'username') and entity.username:
                                large_chats.append(f"@{entity.username}")
                            elif hasattr(entity, 'id'):
                                large_chats.append(str(entity.id))
                    except:
                        continue
            
            await client.disconnect()
            
            if not large_chats:
                await update.message.reply_text("❌ Не найдено чатов с 1000+ участниками. Используйте ручной ввод.")
                return MODE
            
            context.user_data['recipients'] = ", ".join(large_chats)
            context.user_data['parsed_recipients'] = large_chats
            
            await update.message.reply_text(f"✅ Найдено чатов: {len(large_chats)}")
            
            message_text = """
СООБЩЕНИЕ ДЛЯ РАССЫЛКИ

Введите текст сообщения:Поддерживается: текст, эмодзи, разметка
            """
            await update.message.reply_text(message_text)
            return MESSAGE_TEXT
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка поиска чатов: {e}\nПопробуйте ручной ввод.")
            return MODE
    
    else:
        await update.message.reply_text("❌ Введите 1 или 2:")
        return MODE

async def broadcast_recipients(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка получателей (ручной ввод)"""
    recipients_text = update.message.text
    context.user_data['recipients'] = recipients_text
    
    # Парсим получателей
    recipients = [r.strip() for r in recipients_text.split(',')]
    context.user_data['parsed_recipients'] = recipients
    
    message_text = """
СООБЩЕНИЕ ДЛЯ РАССЫЛКИ

Введите текст сообщения:

Поддерживается: текст, эмодзи, разметка
    """
    await update.message.reply_text(message_text)
    return MESSAGE_TEXT

async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текста сообщения"""
    message_text = update.message.text
    context.user_data['message'] = message_text
    
    cycles_text = """
КОЛИЧЕСТВО ПОВТОРЕНИЙ

Введите сколько раз повторить рассылку:
Пример: 5 (отправит 5 раз)

Максимальное количество: 1007
    """
    await update.message.reply_text(cycles_text)
    return CYCLES

async def broadcast_cycles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка количества циклов"""
    try:
        cycles = int(update.message.text)
        if cycles < 1 or cycles > 1007:
            await update.message.reply_text("❌ Количество должно быть от 1 до 1007. Попробуйте снова:")
            return CYCLES
        
        context.user_data['cycles'] = cycles
        
        interval_text = """
ИНТЕРВАЛ МЕЖДУ РАССЫЛКАМИ

Введите интервал в секундах между повторными рассылками:
Рекомендуемый интервал: 60-300 секунд
Максимальный интервал: 600 секунд

Важно: Большой интервал снижает риск блокировки
        """
        await update.message.reply_text(interval_text)
        return INTERVAL
        
    except ValueError:
        await update.message.reply_text("❌ Введите число от 1 до 1007. Попробуйте снова:")
        return CYCLES

async def broadcast_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка интервала"""
    try:
        interval = int(update.message.text)
        if interval < 1 or interval > 600:
            await update.message.reply_text("❌ Интервал должен быть от 1 до 600 секунд. Попробуйте снова:")
            return INTERVAL
        
        context.user_data['interval'] = interval
        
        # Показываем подтверждение
        recipients = context.user_data['parsed_recipients']
        cycles = context.user_data['cycles']
        interval = context.user_data['interval']
        message_preview = context.user_data['message'][:100] + "..." if len(context.user_data['message']) > 100 else context.user_data['message']
        
        # Расчет времени
        total_time_minutes = (cycles * interval) // 60
        
        confirmation_text = f"""
ПОДТВЕРЖДЕНИЕ МАССОВОЙ РАССЫЛКИ

Количество получателей: {len(recipients)}
Количество повторений: {cycles}
Интервал между рассылками: {interval} секунд
Текст сообщения: {message_preview}

Примерное время выполнения: {total_time_minutes} минут

ВНИМАНИЕ: Рассылка начнется сразу после подтверждения!
ВАЖНО: Если вам наложят спамблок или заморозят аккаунт, администрация не несет ответственность

Для подтверждения введите: ПОДТВЕРЖДАЮ
        """
        await update.message.reply_text(confirmation_text)
        return CONFIRM
        
    except ValueError:
        await update.message.reply_text("❌ Введите число от 1 до 600. Попробуйте снова:")
        return INTERVAL

async def broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение и запуск рассылки"""
    if update.message.text.upper() != "ПОДТВЕРЖДАЮ":
        await update.message.reply_text("❌ Рассылка отменена.Для начала новой используйте /broadcast")
        return ConversationHandler.END
    
    user_id = update.effective_user.id
    recipients = context.user_data['parsed_recipients']
    message = context.user_data['message']
    cycles = context.user_data['cycles']
    interval = context.user_data['interval']
    
    # Сохраняем данные рассылки
    active_broadcasts[user_id] = {
        'recipients': recipients,
        'message': message,
        'cycles': cycles,
        'interval': interval,
        'current_cycle': 0,
        'is_running': True,
        'success_count': 0,
        'error_count': 0
    }
    
    # Запускаем рассылку в фоне
    asyncio.create_task(run_broadcast(update, context, user_id))
    
    await update.message.reply_text("✅ Рассылка запущена! Для остановки используйте /stop_broadcast")
    return ConversationHandler.END

async def send_message_safe(client, recipient, message):
    """Безопасная отправка сообщения с обработкой ошибок"""
    try:
        await client.send_message(recipient, message)
        return True
    except Exception as e:
        print(f"Ошибка отправки {recipient}: {e}")
        return False

async def run_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Запуск рассылки в фоне"""
    broadcast_data = active_broadcasts.get(user_id)
    if not broadcast_data:
        return
    
    try:
        client = TelegramClient(StringSession(user_sessions[user_id]), API_ID, API_HASH)
        await client.connect()
        
        for cycle in range(broadcast_data['cycles']):
            if not broadcast_data['is_running']:
                break
                
            broadcast_data['current_cycle'] = cycle + 1
            
            # Отправляем сообщение о начале цикла
            progress_text = f"""
🔄 ЗАПУСК ЦИКЛА {cycle + 1}/{broadcast_data['cycles']}

Отправляю сообщения одновременно во все чаты...

/stop_broadcast - остановить рассылку
            """
            await context.bot.send_message(chat_id=user_id, text=progress_text)
            
            # СОЗДАЕМ ЗАДАЧИ ДЛЯ ОДНОВРЕМЕННОЙ ОТПРАВКИ
            tasks = []
            for recipient in broadcast_data['recipients']:
                if not broadcast_data['is_running']:
                    break
                # Создаем задачу для каждого получателя
                task = send_message_safe(client, recipient, broadcast_data['message'])
                tasks.append(task)
            
            # ЗАПУСКАЕМ ВСЕ ЗАДАЧИ ОДНОВРЕМЕННО
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Считаем результаты
            success_count = sum(1 for result in results if result is True)
            error_count = len(results) - success_count
            
            # Обновляем статистику
            broadcast_data['success_count'] += success_count
            broadcast_data['error_count'] += error_count
            
            # Отправляем отчет о цикле
            cycle_report = f"""
✅ ЦИКЛ {cycle + 1}/{broadcast_data['cycles']} ЗАВЕРШЕН

Успешно: {success_count}
Ошибки: {error_count}
Всего отправлено: {broadcast_data['success_count']}
Всего ошибок: {broadcast_data['error_count']}
            """
            await context.bot.send_message(chat_id=user_id, text=cycle_report)
            
            # Ждем только перед следующим циклом (если он есть)
            if cycle < broadcast_data['cycles'] - 1 and broadcast_data['is_running']:
                wait_text = f"""
⏳ ОЖИДАНИЕ СЛЕДУЮЩЕГО ЦИКЛА

Следующий цикл через: {broadcast_data['interval']} секунд
Текущий цикл: {cycle + 1}/{broadcast_data['cycles']}
Осталось циклов: {broadcast_data['cycles'] - (cycle + 1)}
                """
                await context.bot.send_message(chat_id=user_id, text=wait_text)
                await asyncio.sleep(broadcast_data['interval'])
        
        # Завершение рассылки
        if broadcast_data['is_running']:
            completion_text = f"""
🎉 РАССЫЛКА ЗАВЕРШЕНА

Успешно отправлено: {broadcast_data['success_count']}Ошибки: {broadcast_data['error_count']}
Завершено циклов: {broadcast_data['current_cycle']}/{broadcast_data['cycles']}
            """
            await context.bot.send_message(chat_id=user_id, text=completion_text)
        
        await client.disconnect()
        
    except Exception as e:
        error_text = f"❌ Ошибка рассылки: {e}"
        await context.bot.send_message(chat_id=user_id, text=error_text)
    
    finally:
        if user_id in active_broadcasts:
            del active_broadcasts[user_id]

async def stop_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Остановка рассылки"""
    user_id = update.effective_user.id
    
    if user_id in active_broadcasts:
        active_broadcasts[user_id]['is_running'] = False
        
        stats = active_broadcasts[user_id]
        stop_text = f"""
🛑 ВАША РАССЫЛКА ОСТАНОВЛЕНА

Результаты на момент остановки:
- Успешно отправлено: {stats['success_count']}
- Ошибки: {stats['error_count']}
- Завершено циклов: {stats['current_cycle']}/{stats['cycles']}

Для начала новой рассылки используйте: /broadcast
        """
        await update.message.reply_text(stop_text)
        del active_broadcasts[user_id]
    else:
        await update.message.reply_text("❌ У вас нет активных рассылок")

async def my_broadcasts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Мои активные рассылки"""
    user_id = update.effective_user.id
    
    if user_id in active_broadcasts:
        stats = active_broadcasts[user_id]
        status_text = f"""
📊 АКТИВНАЯ РАССЫЛКА

Текущий цикл: {stats['current_cycle']}/{stats['cycles']}
Успешно отправлено: {stats['success_count']}
Ошибки: {stats['error_count']}
Статус: {'🟢 Запущена' if stats['is_running'] else '🟡 Останавливается'}

/stop_broadcast - остановить рассылку
        """
        await update.message.reply_text(status_text)
    else:
        await update.message.reply_text("❌ У вас нет активных рассылок")

async def broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена настройки рассылки"""
    await update.message.reply_text("❌ Настройка рассылки отменена.")
    return ConversationHandler.END

def main():
    """Запуск бота"""
    try:
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Обработчик авторизации
        auth_conv = ConversationHandler(
            entry_points=[CommandHandler('auth', auth_start)],
            states={
                PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, auth_phone)],
                CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, auth_code)],
                PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, auth_password)],
            },
            fallbacks=[CommandHandler('cancel', auth_cancel)]
        )
        
        # Обработчик рассылки
        broadcast_conv = ConversationHandler(
            entry_points=[CommandHandler('broadcast', broadcast_start)],
            states={
                MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_mode)],
                RECIPIENTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_recipients)],
                MESSAGE_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_message)],
                CYCLES: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_cycles)],
                INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_interval)],
                CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_confirm)],
            },
            fallbacks=[CommandHandler('cancel', broadcast_cancel)]
        )
        
        # Регистрируем обработчики
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("status", status))
        application.add_handler(CommandHandler("stop_broadcast", stop_broadcast))
        application.add_handler(CommandHandler("my_broadcasts", my_broadcasts))
        application.add_handler(auth_conv)
        application.add_handler(broadcast_conv)
        
        print("✅ Бот Moga запущен с одновременной отправкой!")
        application.run_polling()
        
    except Exception as e:
        print(f"❌ Ошибка при запуске: {e}")

if __name__ == "__main__":
    main()
