import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import os
import webbrowser
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

if ENV_PATH.exists():
    load_dotenv(ENV_PATH)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
APP_VERSION = os.getenv("APP_VERSION", "4.5.0")
LATEST_VERSION = os.getenv("LATEST_VERSION", APP_VERSION)
UPDATE_URL = os.getenv("UPDATE_URL", "")  # можно добавить позже


bot_process = None


def start_bot():
    global bot_process
    if bot_process is not None and bot_process.poll() is None:
        messagebox.showinfo("CryptoBay", "Бот уже запущен.")
        return

    try:
        # Запуск: python -m bot.main_bot
        bot_process = subprocess.Popen(
            ["python", "-m", "bot.main_bot"],
            cwd=str(BASE_DIR),
        )
        messagebox.showinfo("CryptoBay", "Бот запущен.")
        status_var.set("Статус: бот запущен")
    except Exception as e:
        messagebox.showerror("Ошибка", f"Не удалось запустить бота:\n{e}")


def stop_bot():
    global bot_process
    if bot_process is None:
        messagebox.showinfo("CryptoBay", "Бот ещё не запускался.")
        return

    if bot_process.poll() is not None:
        bot_process = None
        status_var.set("Статус: бот уже остановлен")
        messagebox.showinfo("CryptoBay", "Бот уже остановлен.")
        return

    try:
        bot_process.terminate()
        try:
            bot_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            bot_process.kill()
        status_var.set("Статус: бот остановлен")
        messagebox.showinfo("CryptoBay", "Бот остановлен.")
    except Exception as e:
        messagebox.showerror("Ошибка", f"Не удалось остановить бота:\n{e}")
    finally:
        bot_process = None


def open_telegram():
    webbrowser.open("https://t.me/criptobay_bot")


def _parse_version(v: str):
    parts = []
    for p in v.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def check_updates():
    cur = APP_VERSION
    latest = LATEST_VERSION

    try:
        cur_t = _parse_version(cur)
        lat_t = _parse_version(latest)
    except Exception:
        cur_t = (0,)
        lat_t = (0,)

    if lat_t > cur_t:
        text = f"Доступна новая версия: {latest}\nТекущая версия: {cur}"
        if UPDATE_URL:
            text += "\n\nОткрыть страницу обновления?"
            if messagebox.askyesno("Обновление доступно", text):
                webbrowser.open(UPDATE_URL)
        else:
            messagebox.showinfo("Обновление доступно", text)
    else:
        messagebox.showinfo(
            "Обновления",
            f"У вас актуальная версия: {cur}",
        )


# === GUI ===

root = tk.Tk()
root.title("CryptoBay Bot Manager")
root.geometry("520x320")

style = ttk.Style()
style.configure("TButton", font=("Segoe UI", 10))
style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"))

header = ttk.Label(root, text="CryptoBay Bot Manager", style="Header.TLabel")
header.pack(pady=10)

version_label = ttk.Label(root, text=f"Версия приложения: {APP_VERSION}")
version_label.pack(pady=2)

status_var = tk.StringVar(value="Статус: бот остановлен")
status_label = ttk.Label(root, textvariable=status_var)
status_label.pack(pady=2)

frame = ttk.Frame(root)
frame.pack(pady=15, fill="x", padx=30)

btn_start = ttk.Button(frame, text="🚀 Запустить бота", command=start_bot)
btn_start.pack(fill="x", pady=3)

btn_stop = ttk.Button(frame, text="⏹ Остановить бота", command=stop_bot)
btn_stop.pack(fill="x", pady=3)

btn_tg = ttk.Button(frame, text="📱 Открыть Telegram", command=open_telegram)
btn_tg.pack(fill="x", pady=3)

btn_update = ttk.Button(frame, text="🔄 Проверить обновления", command=check_updates)
btn_update.pack(fill="x", pady=3)

btn_exit = ttk.Button(frame, text="❌ Выход", command=root.destroy)
btn_exit.pack(fill="x", pady=10)

footer = ttk.Label(
    root,
    text="CryptoBay Pro • 2025",
    font=("Segoe UI", 9),
    foreground="gray",
)
footer.pack(side="bottom", pady=5)

root.mainloop()
