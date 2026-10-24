# VHS-Sat

Домашний стриминговый сервер с поддержкой локальных каналов (LokalChanel),
ретрансляции DVB-S/S2 (Linux), HLS и multicast MPEG-TS.

## 🚀 О проекте

VHS-Sat — это независимый проект, вдохновлённый архитектурными паттернами
проекта [VHS-Streamer](https://github.com/andrey-geben/VHS-Streamer).
Однако это полностью самостоятельная разработка с другим набором функций
и фокусом на домашнее использование.

## 👤 Автор

**Andrew Genben**

## 🛠️ Стек технологий
- **Backend:** Python, Flask
- **Хранение данных:** SQLite, YAML
- **Медиа:** FFmpeg, dvblast (только для Linux)

## 📋 Требования
- Python 3.10+
- FFmpeg
- (Опционально, для DVB) Linux, dvblast, dvb-apps

## ⚙️ Установка и запуск
```bash
# 1. Клонировать репозиторий
git clone https://github.com/ваш-username/VHS-Sat.git
cd VHS-Sat

# 2. Создать виртуальное окружение и установить зависимости
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux: source .venv/bin/activate
pip install -r requirements.txt

# 3. Настроить конфигурацию
cp config.example.yaml config.yaml
# Отредактируйте config.yaml, указав свои пути и данные

# 4. Запустить сервер
python server.py