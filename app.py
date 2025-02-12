import os
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from werkzeug.utils import secure_filename
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account

app = Flask(__name__)

# Настройки базы данных SQLite
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///orders.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Настройки почты (Gmail SMTP)
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # 1 ГБ
app.config['MAIL_SERVER'] = 'smtp.mail.ru'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USERNAME'] = 'gorunum@mail.ru'
app.config['MAIL_PASSWORD'] = 'uCEbshNMx3uSV2YyEXNv'
app.config['MAIL_DEFAULT_SENDER'] = 'gorunum@mail.ru'

mail = Mail(app)

# Google Drive API
import json
import os
import shutil

MAX_STORAGE_MB = 10000  # 10 ГБ

def get_folder_size(folder):
    """Подсчитывает общий размер папки в мегабайтах."""
    total_size = 0
    for dirpath, _, filenames in os.walk(folder):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.exists(fp):
                total_size += os.path.getsize(fp)
    return total_size / (1024 * 1024)  # Преобразуем в MB

def cleanup_storage(folder="uploads"):
    """Удаляет старые файлы, если размер хранилища превышает лимит."""
    if not os.path.exists(folder):
        return
    
    while get_folder_size(folder) > MAX_STORAGE_MB:
        files = [(f, os.path.getctime(os.path.join(folder, f))) for f in os.listdir(folder)]
        files.sort(key=lambda x: x[1])  # Сортируем по дате создания (старые файлы первыми)

        if files:
            oldest_file = os.path.join(folder, files[0][0])
            print(f"🗑 Удаляем файл {oldest_file}, так как хранилище заполнено!")
            os.remove(oldest_file)
        else:
            break

SCOPES = ['https://www.googleapis.com/auth/drive.file']
FOLDER_ID = '1FPnyzcyYvQn0fTNpdVf-PazNJBUARpni'  # ID твоей папки на Google Drive 

# Читаем API-ключ из переменной окружения GOOGLE_CREDENTIALS
SERVICE_ACCOUNT_INFO = json.loads(os.environ.get("GOOGLE_CREDENTIALS"))
credentials = service_account.Credentials.from_service_account_info(
SERVICE_ACCOUNT_INFO, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=credentials)

from datetime import datetime, timedelta

def delete_old_files(days=7):
    """Удаляет файлы из Google Drive, которым больше `days` дней."""
    cutoff_date = (datetime.utcnow() - timedelta(days=days)).isoformat() + 'Z'
    query = f"'{FOLDER_ID}' in parents and modifiedTime < '{cutoff_date}'"
    results = drive_service.files().list(q=query, fields="files(id, name, modifiedTime)").execute()
    files = results.get('files', [])

    if not files:
        print("✅ Нет старых файлов для удаления.")
        return

    print(f"🔍 Найдено {len(files)} старых файлов для удаления...")

    for file in files:
        try:
            drive_service.files().delete(fileId=file['id']).execute()
            print(f"🗑️ Удалён файл: {file['name']} (ID: {file['id']})")
        except Exception as e:
            print(f"❌ Ошибка удаления файла {file['name']}: {str(e)}")

def upload_to_drive(file_path, filename):
    """Загрузка файла в Google Drive и получение ссылки."""
    file_metadata = {'name': filename, 'parents': [FOLDER_ID]}
    media = MediaFileUpload(file_path, resumable=True)
    file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    return f"https://drive.google.com/file/d/{file['id']}/view"

# Модель базы данных
class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    store_name = db.Column(db.String(255), nullable=False)
    order_number = db.Column(db.String(50), nullable=False)
    comment = db.Column(db.Text, nullable=True)
    file_url = db.Column(db.String(255), nullable=False)

# Создание базы данных
with app.app_context():
    db.create_all()

import threading

def process_file_async(file_path, filename):
    """Функция загружает файл в фоне, чтобы Render не убивал процесс."""
    thread = threading.Thread(target=upload_to_drive, args=(file_path, filename))
    thread.start()

# Обработчик формы
@app.route('/submit', methods=['POST'])
def submit_form():
    store_name = request.form.get('store_name')
    order_number = request.form.get('order_number')
    comment = request.form.get('comment', '')

    if not store_name or not order_number:
        return jsonify({'error': 'Название заведения и номер заказа обязательны'}), 400

    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'Файл обязателен'}), 400

    filename = secure_filename(file.filename)
    file_path = os.path.join("uploads", filename)  # Сохраняем в папку uploads
    cleanup_storage("uploads") # Проверяем, если хранилище заполнено, удаляем старые файлы
    os.makedirs("uploads", exist_ok=True)  # Создаём папку, если её нет
    file.save(file_path)

    # Загружаем файл в Google Drive
    process_file_async(file_path, filename)
    file_url = "Uploading file to Drive..."  # Временная заглушка, пока идёт загрузка


    # Сохраняем в базе данных
    new_order = Order(store_name=store_name, order_number=order_number, comment=comment, file_url=file_url)
    db.session.add(new_order)
    db.session.commit()

    # Отправка email
    msg = Message(f"{store_name} - #{order_number}", recipients=["woltvideo@gmail.com"])
    msg.body = f"""
    Venue name: {store_name}
    Order number: {order_number}
    Comment: {comment or 'left blank'}

    📂 Google Drive Link: {file_url}
    """

    # Прикрепляем файл к email
    with open(file_path, "rb") as fp:
        msg.attach(filename, "application/octet-stream", fp.read())

    # Добавляем заголовки, чтобы письмо не ушло в спам
    msg.headers = {
        "X-Mailer": "Flask-Mail",
        "X-Priority": "3",
        "Precedence": "bulk",
    }

    msg.reply_to = "support@wolt.com"
    mail.send(msg)
    os.remove(file_path)

    return jsonify({'message': 'Заявка отправлена и сохранена', 'file_url': file_url}), 200  # ✅ Теперь return на правильном уровне

from flask import render_template
from flask import send_from_directory

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico', mimetype='image/vnd.microsoft.icon')


# Главная страница с формой
@app.route('/')
def index():
    return render_template('index.html')  # Загружаем HTML-форму


import threading
import requests
import time

def keep_alive():
    """Функция отправляет запросы к сайту, чтобы Render не засыпал"""
    while True:
        try:
            requests.get("https://flask-order-report.onrender.com")
            print("✅ Keep-alive запрос отправлен!")
        except Exception as e:
            print("❌ Ошибка при пинге сайта:", e)
        time.sleep(300)  # 300 секунд = 5 минут

# Запускаем keep_alive в отдельном потоке
thread = threading.Thread(target=keep_alive, daemon=True)
thread.start()

if __name__ == '__main__':
    print("🚀 Запуск сервера...")
    delete_old_files(days=7)  # Удаляем файлы старше 7 дней
    app.run(debug=True)


