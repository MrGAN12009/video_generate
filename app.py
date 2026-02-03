from flask import Flask, render_template, request, jsonify, send_file
import threading
import os
import time
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Хранилище состояния задач
tasks = {}

def generate_video_with_progress(prompt, task_id):
    """Генерация видео с отслеживанием прогресса"""
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

        tasks[task_id] = {
            "status": "started",
            "progress": 0,
            "message": "Генерация видео началась",
            "video_id": video.id
        }

        while video.status in ("in_progress", "queued"):
            video = client.videos.retrieve(video.id)
            progress = getattr(video, "progress", 0)

            status_text = "В очереди" if video.status == "queued" else "Обработка"
            
            tasks[task_id] = {
                "status": video.status,
                "progress": progress,
                "message": status_text,
                "video_id": video.id
            }
            
            time.sleep(5)

        if video.status == "failed":
            message = getattr(
                getattr(video, "error", None), "message", "Генерация видео не удалась"
            )
            tasks[task_id] = {
                "status": "failed",
                "progress": 100,
                "message": message,
                "video_id": video.id
            }
        else:
            tasks[task_id] = {
                "status": "downloading",
                "progress": 95,
                "message": "Скачивание видео...",
                "video_id": video.id
            }

            try:
                content = client.videos.download_content(video.id, variant="video")
                video_path = f"video_{task_id}.mp4"
                content.write_to_file(video_path)
                
                # Проверяем, что файл действительно создан
                if not os.path.exists(video_path):
                    raise Exception("Файл не был создан после сохранения")
                
                tasks[task_id] = {
                    "status": "completed",
                    "progress": 100,
                    "message": "Генерация завершена",
                    "video_id": video.id,
                    "video_path": video_path
                }
            except Exception as download_error:
                tasks[task_id] = {
                    "status": "error",
                    "progress": 95,
                    "message": f"Ошибка при скачивании: {str(download_error)}",
                    "video_id": video.id
                }
                raise
    except Exception as e:
        tasks[task_id] = {
            "status": "error",
            "progress": 0,
            "message": f"Ошибка: {str(e)}",
            "video_id": None
        }

@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate():
    """Запуск генерации видео"""
    prompt = request.json.get('prompt', '')
    if not prompt:
        return jsonify({"error": "Промпт не может быть пустым"}), 400
    
    import uuid
    task_id = str(uuid.uuid4())
    
    tasks[task_id] = {
        "status": "queued",
        "progress": 0,
        "message": "Задача поставлена в очередь",
        "video_id": None
    }
    
    # Запускаем генерацию в отдельном потоке
    thread = threading.Thread(target=generate_video_with_progress, args=(prompt, task_id))
    thread.daemon = True
    thread.start()
    
    return jsonify({"task_id": task_id})

@app.route('/status/<task_id>')
def status(task_id):
    """Получение статуса задачи"""
    if task_id not in tasks:
        return jsonify({"error": "Задача не найдена"}), 404
    
    task = tasks[task_id]
    return jsonify(task)

@app.route('/download/<task_id>')
def download(task_id):
    """Скачивание готового видео"""
    if task_id not in tasks:
        return jsonify({"error": "Задача не найдена"}), 404
    
    task = tasks[task_id]
    
    # Если есть путь к файлу, проверяем его наличие
    video_path = None
    if "video_path" in task:
        video_path = task["video_path"]
    else:
        # Пытаемся найти файл по стандартному имени
        possible_path = f"video_{task_id}.mp4"
        if os.path.exists(possible_path):
            video_path = possible_path
            # Обновляем задачу
            task["video_path"] = video_path
            if task["status"] == "downloading":
                task["status"] = "completed"
    
    if not video_path:
        return jsonify({
            "error": "Путь к видео не найден",
            "status": task["status"],
            "message": task.get("message", "Ожидание...")
        }), 400
    
    if not os.path.exists(video_path):
        return jsonify({
            "error": "Файл не найден на диске",
            "video_path": video_path,
            "status": task["status"]
        }), 404
    
    # Проверяем статус (разрешаем скачивание если файл существует, даже если статус "downloading")
    if task["status"] not in ("completed", "downloading"):
        return jsonify({
            "error": "Видео ещё не готово",
            "status": task["status"],
            "message": task.get("message", "Ожидание...")
        }), 400
    
    try:
        return send_file(video_path, as_attachment=True, download_name="video.mp4")
    except Exception as e:
        return jsonify({"error": f"Ошибка при отправке файла: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)

