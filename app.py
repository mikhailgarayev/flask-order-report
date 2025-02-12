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
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'ratemikhail@gmail.com'  # Замени на свою почту
app.config['MAIL_PASSWORD'] = 'jyjg lajr ksuc kjes'  # Вставь пароль от почты
app.config['MAIL_DEFAULT_SENDER'] = 'ratemikhail@gmail.com'

mail = Mail(app)

# Google Drive API
SCOPES = ['https://www.googleapis.com/auth/drive.file']
SERVICE_ACCOUNT_FILE = 'credentials.json'  # Файл ключа сервисного аккаунта
FOLDER_ID = '1a6rYC0tMjKgIUnrIdrKTO59QUML1VDsA'  # ID твоей папки на Google Drive

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
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
    file_path = filename
    file.save(file_path)

    # Загружаем файл в Google Drive
    file_url = upload_to_drive(file_path, filename)

    # Удаляем временный файл
    os.remove(file_path)

    # Сохраняем в базе данных
    new_order = Order(store_name=store_name, order_number=order_number, comment=comment, file_url=file_url)
    db.session.add(new_order)
    db.session.commit()

    # Отправка email
    msg = Message(f"New video from {store_name}", recipients=["ratemikhail@gmail.com"])
    msg.body = f"Venue name: {store_name}\nOrder number: {order_number}\nComment: {comment or 'Left blank'}\nLink to file: {file_url}"
    mail.send(msg)

    return jsonify({'message': 'Заявка отправлена и сохранена', 'file_url': file_url}), 200
from flask import render_template

# Главная страница с формой
@app.route('/')
def index():
    return render_template('index.html')  # Загружаем HTML-форму


if __name__ == '__main__':
    print("🚀 Запуск сервера...")
    delete_old_files(days=7)  # Удаляем файлы старше 7 дней
    app.run(debug=True)

