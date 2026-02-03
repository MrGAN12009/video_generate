import telebot
from telebot import types
from request import generate_video
import threading
import os
import time
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Получаем токен бота из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения. Добавьте его в .env файл")

bot = telebot.TeleBot(BOT_TOKEN)

# Хранилище состояния задач пользователей
user_tasks = {}

def generate_video_with_progress(prompt, user_id, message_id):
    """Генерация видео с отслеживанием прогресса для Telegram"""
    client = OpenAI(
        api_key=f"{os.getenv('API_KEY')}",
        base_url="https://api.proxyapi.ru/openai/v1",
    )

    try:
        video = client.videos.create(
            model="sora-2",
            prompt=f"{prompt}",
            seconds="4",
        )

        user_tasks[user_id] = {
            "status": "started",
            "progress": 0,
            "message": "Генерация видео началась",
            "video_id": video.id
        }
        
        update_progress_message(user_id, message_id, "started", 0, "Генерация видео началась")

        while video.status in ("in_progress", "queued"):
            video = client.videos.retrieve(video.id)
            progress = getattr(video, "progress", 0)

            status_text = "В очереди" if video.status == "queued" else "Обработка"
            
            user_tasks[user_id] = {
                "status": video.status,
                "progress": progress,
                "message": status_text,
                "video_id": video.id
            }
            
            update_progress_message(user_id, message_id, video.status, progress, status_text)
            time.sleep(5)

        if video.status == "failed":
            message = getattr(
                getattr(video, "error", None), "message", "Генерация видео не удалась"
            )
            user_tasks[user_id] = {
                "status": "failed",
                "progress": 100,
                "message": message,
                "video_id": video.id
            }
            update_progress_message(user_id, message_id, "failed", 100, message)
        else:
            user_tasks[user_id] = {
                "status": "downloading",
                "progress": 95,
                "message": "Скачивание видео...",
                "video_id": video.id
            }
            update_progress_message(user_id, message_id, "downloading", 95, "Скачивание видео...")

            content = client.videos.download_content(video.id, variant="video")
            video_path = f"video_{user_id}_{message_id}.mp4"
            content.write_to_file(video_path)

            user_tasks[user_id] = {
                "status": "completed",
                "progress": 100,
                "message": "Генерация завершена",
                "video_id": video.id,
                "video_path": video_path
            }
            
            # Отправляем готовое видео
            try:
                with open(video_path, 'rb') as video_file:
                    bot.send_video(user_id, video_file, caption="✅ Видео готово!")
                # Удаляем файл после отправки
                if os.path.exists(video_path):
                    os.remove(video_path)
            except Exception as e:
                bot.send_message(user_id, f"Ошибка при отправке видео: {str(e)}")
            
            update_progress_message(user_id, message_id, "completed", 100, "✅ Генерация завершена")
            
    except Exception as e:
        user_tasks[user_id] = {
            "status": "error",
            "progress": 0,
            "message": f"Ошибка: {str(e)}",
            "video_id": None
        }
        update_progress_message(user_id, message_id, "error", 0, f"❌ Ошибка: {str(e)}")

def update_progress_message(user_id, message_id, status, progress, message_text):
    """Обновление сообщения с прогресс-баром"""
    try:
        bar_length = 20
        filled_length = int((progress / 100) * bar_length)
        bar = "█" * filled_length + "░" * (bar_length - filled_length)
        
        status_emoji = {
            "started": "🚀",
            "queued": "⏳",
            "in_progress": "⚙️",
            "downloading": "⬇️",
            "completed": "✅",
            "failed": "❌",
            "error": "❌"
        }
        
        emoji = status_emoji.get(status, "⏳")
        
        progress_text = f"{emoji} {message_text}\n\n[{bar}] {progress:.1f}%"
        
        bot.edit_message_text(
            progress_text,
            chat_id=user_id,
            message_id=message_id
        )
    except Exception as e:
        # Игнорируем ошибки редактирования (например, если сообщение не изменилось)
        pass

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Обработчик команд /start и /help"""
    welcome_text = """
🎬 Добро пожаловать в бота для генерации видео через ИИ!

📝 Использование:
Просто отправьте мне описание видео, которое вы хотите создать.

Пример:
"Крупный план чашки горячего кофе на деревянном столе, утренний свет сквозь жалюзи"

⏱️ Генерация занимает некоторое время, вы будете видеть прогресс в реальном времени.
    """
    bot.reply_to(message, welcome_text)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    """Обработчик всех текстовых сообщений"""
    prompt = message.text.strip()
    
    if not prompt:
        bot.reply_to(message, "❌ Пожалуйста, отправьте описание видео.")
        return
    
    # Проверяем, не запущена ли уже задача для этого пользователя
    if message.from_user.id in user_tasks:
        current_task = user_tasks[message.from_user.id]
        if current_task["status"] in ("started", "queued", "in_progress", "downloading"):
            bot.reply_to(message, "⏳ У вас уже есть активная задача генерации. Дождитесь её завершения.")
            return
    
    # Отправляем сообщение о начале генерации
    progress_msg = bot.reply_to(message, "🚀 Генерация видео началась...\n\n[░░░░░░░░░░░░░░░░░░░░] 0.0%")
    
    # Запускаем генерацию в отдельном потоке
    thread = threading.Thread(
        target=generate_video_with_progress,
        args=(prompt, message.from_user.id, progress_msg.message_id)
    )
    thread.daemon = True
    thread.start()

if __name__ == '__main__':
    print("Бот запущен...")
    bot.infinity_polling()

