from openai import OpenAI
import sys
import time
from dotenv import load_dotenv
import os

load_dotenv()

def generate_video(prompt):
    client = OpenAI(
        api_key=f"{os.getenv('API_KEY')}",
        base_url="https://api.proxyapi.ru/openai/v1",
    )

    video = client.videos.create(
        model="sora-2",
        prompt=f"{prompt}",
        seconds="4",
    )

    print("Генерация видео началась:", video)

    progress = getattr(video, "progress", 0)
    bar_length = 30

    while video.status in ("in_progress", "queued"):
        video = client.videos.retrieve(video.id)
        progress = getattr(video, "progress", 0)

        filled_length = int((progress / 100) * bar_length)
        bar = "=" * filled_length + "-" * (bar_length - filled_length)
        status_text = "В очереди" if video.status == "queued" else "Обработка"

        sys.stdout.write(f"\r{status_text}: [{bar}] {progress:.1f}%")
        sys.stdout.flush()
        time.sleep(5)

    sys.stdout.write("\n")

    if video.status == "failed":
        message = getattr(
            getattr(video, "error", None), "message", "Генерация видео не удалась"
        )
        print(message)
    else:
        print("Генерация видео завершена:", video)
        print("Скачивание видео...")

        content = client.videos.download_content(video.id, variant="video")
        content.write_to_file("video.mp4")

        print("Файл video.mp4 сохранён")

generate_video("Крупный план чашки горячего кофе на деревянном столе, утренний свет сквозь жалюзи, мягкая глубина резкости.")