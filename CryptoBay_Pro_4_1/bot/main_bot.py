import asyncio
import logging
import os
import json
import datetime as dt
from pathlib import Path
from typing import Dict, Any, List, Optional

import requests
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    FSInputFile,
)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# === Пути и окружение ===

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
DATA_DIR = BASE_DIR / "data"
CHARTS_DIR = BASE_DIR / "charts"
LOGS_DIR = BASE_DIR / "logs"

for d in (DATA_DIR, CHARTS_DIR, LOGS_DIR):
    d.mkdir(parents=True, exist_ok=True)

print(f"ENV файл: {ENV_PATH}")
load_dotenv(ENV_PATH)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "0") or "0")
APP_VERSION = os.getenv("APP_VERSION", "4.1.0")
ALERT_THRESHOLD = float(os.getenv("ALERT_THRESHOLD_PERCENT", "2.0"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден в .env")

# === Логирование ===

logger = logging.getLogger("cryptobay.bot")
logger.setLevel(logging.INFO)

fmt = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

file_handler = logging.FileHandler(LOGS_DIR / "bot.log", encoding="utf-8")
file_handler.setFormatter(fmt)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(fmt)
logger.addHandler(console_handler)

logger.info("Запуск CryptoBay бота…")

# === Инициализация бота ===

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# В памяти храним настройки уведомлений
ALERT_ENABLED = set()  # user_ids: set[int]

# Файл с портфелями
PORTFOLIO_FILE = DATA_DIR / "portfolio.json"

# Разрешённые монеты для портфеля/обмена
SYMBOL_TO_COINGECKO = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "USDT": "tether",
}

# === Хелперы портфеля ===

def load_portfolio() -> Dict[str, Any]:
    if not PORTFOLIO_FILE.exists():
        return {}
    try:
        with PORTFOLIO_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.exception("Ошибка чтения файла портфеля")
        return {}


def save_portfolio(data: Dict[str, Any]) -> None:
    try:
        with PORTFOLIO_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.exception("Ошибка сохранения файла портфеля")


def format_usd(value: float) -> str:
    return f"{value:,.2f} $".replace(",", " ")

# === Запросы к API ===

def get_btc_overview() -> Optional[Dict[str, Any]]:
    """
    BTC: цена, % за 24ч, капитализация, объём.
    """
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "ids": "bitcoin",
        "price_change_percentage": "24h",
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if not data:
            return None
        coin = data[0]
        return {
            "price": coin.get("current_price"),
            "change_24h": coin.get("price_change_percentage_24h"),
            "market_cap": coin.get("market_cap"),
            "volume_24h": coin.get("total_volume"),
        }
    except Exception as e:
        logger.error("Ошибка запроса BTC с CoinGecko: %s", e)
        return None


def get_top10() -> Optional[List[Dict[str, Any]]]:
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": 10,
        "page": 1,
        "price_change_percentage": "24h",
    }
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        logger.info("Топ-10 получен с CoinGecko")
        return data
    except Exception as e:
        logger.error("Ошибка запроса топ-10: %s", e)
        return None


def get_prices_for_symbols(symbols: List[str]) -> Dict[str, float]:
    """
    Возвращает цены по символам в USD.
    Пока поддерживаем BTC/ETH/USDT.
    """
    ids = []
    reverse = {}
    for sym in symbols:
        sym_up = sym.upper()
        if sym_up in SYMBOL_TO_COINGECKO:
            cid = SYMBOL_TO_COINGECKO[sym_up]
            ids.append(cid)
            reverse[cid] = sym_up
    if not ids:
        return {}

    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": ",".join(ids),
        "vs_currencies": "usd",
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        prices = {}
        for cid, item in data.items():
            sym = reverse.get(cid)
            if sym and "usd" in item:
                prices[sym] = float(item["usd"])
        return prices
    except Exception as e:
        logger.error("Ошибка запроса simple/price: %s", e)
        return {}


def build_btc_chart_png() -> Optional[str]:
    """
    Строим график BTC/USDT за 24 часа по Binance.
    """
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": "BTCUSDT",
        "interval": "1h",
        "limit": 24,
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        klines = r.json()
        logger.info("График BTC получен с Binance")
    except Exception as e:
        logger.error("Ошибка запроса графика с Binance: %s", e)
        return None

    try:
        times = [dt.datetime.fromtimestamp(int(k[0]) / 1000) for k in klines]
        closes = [float(k[4]) for k in klines]

        out_path = CHARTS_DIR / "btc_24h.png"
        plt.figure(figsize=(9, 4))
        plt.plot(times, closes)
        plt.title("BTC/USDT — последние 24 часа (Binance)")
        plt.xlabel("Время")
        plt.ylabel("Цена, USDT")
        plt.grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig(out_path)
        plt.close()
        return str(out_path)
    except Exception as e:
        logger.error("Ошибка построения графика BTC: %s", e)
        return None

# === Клавиатура ===

def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Курсы"),
                KeyboardButton(text="📈 График BTC"),
            ],
            [
                KeyboardButton(text="🏆 Топ-10"),
                KeyboardButton(text="💼 Мой портфель"),
            ],
            [
                KeyboardButton(text="🔁 Обменять"),
                KeyboardButton(text="🔔 Уведомления"),
            ],
            [
                KeyboardButton(text="☎ Поддержка"),
            ],
        ],
        resize_keyboard=True,
    )

# === Хендлеры ===

@dp.message(CommandStart())
async def handle_start(message: Message) -> None:
    logger.info("Пользователь %s запустил /start", message.from_user.id)
    text = (
        "👋 Привет! Это <b>CryptoBay Pro</b>.\n\n"
        "Я умею:\n"
        "• Показать актуальные курсы\n"
        "• Построить график BTC за 24ч\n"
        "• Показать топ-10 монет\n"
        "• Вести твой мини-портфель\n"
        "• Делать быстрый обмен\n"
        "• Присылать авто-уведомления об изменении цены\n\n"
        "Выбирай действие ниже 👇"
    )
    await message.answer(text, reply_markup=main_keyboard())


@dp.message(F.text == "📊 Курсы")
async def handle_rates(message: Message) -> None:
    logger.info("Курсы запрошены пользователем %s", message.from_user.id)
    btc = get_btc_overview()
    if not btc:
        await message.answer("⚠ Не удалось получить курс BTC. Попробуй чуть позже.")
        return

    price = btc["price"]
    ch = btc["change_24h"]
    mc = btc["market_cap"]
    vol = btc["volume_24h"]

    arrow = "🔺" if ch and ch > 0 else "🔻"
    text = (
        "<b>BTC / USD</b>\n"
        f"Цена: <b>{format_usd(price)}</b>\n"
        f"Изм. за 24ч: {arrow} {ch:+.2f}%\n\n"
        f"Капитализация: {format_usd(mc)}\n"
        f"Объём (24ч): {format_usd(vol)}"
    )
    await message.answer(text)


@dp.message(F.text == "📈 График BTC")
async def handle_chart(message: Message) -> None:
    logger.info("График запрошен пользователем %s", message.from_user.id)
    await message.answer("⏳ Строю график BTC за 24 часа…")
    path = await asyncio.to_thread(build_btc_chart_png)
    if not path:
        await message.answer("⚠ Не удалось построить график. Попробуй позже.")
        return
    photo = FSInputFile(path)
    await message.answer_photo(photo, caption="BTC/USDT — последние 24 часа (Binance)")


@dp.message(F.text == "🏆 Топ-10")
async def handle_top10(message: Message) -> None:
    logger.info("Топ-10 запрошен пользователем %s", message.from_user.id)
    data = get_top10()
    if not data:
        await message.answer("⚠ Не удалось получить топ-10 монет. Попробуй позже.")
        return

    lines = ["<b>🏆 Топ-10 монет по капитализации</b>\n"]
    for i, coin in enumerate(data, start=1):
        name = coin.get("name")
        sym = coin.get("symbol", "").upper()
        price = coin.get("current_price")
        ch = coin.get("price_change_percentage_24h") or 0.0
        mc = coin.get("market_cap") or 0.0

        arrow = "🔺" if ch > 0 else "🔻" if ch < 0 else "➖"
        lines.append(
            f"{i}. <b>{name} ({sym})</b>\n"
            f"   Цена: {format_usd(price)} | {arrow} {ch:+.2f}%\n"
            f"   Капа: {format_usd(mc)}\n"
        )

    await message.answer("\n".join(lines))


@dp.message(F.text == "💼 Мой портфель")
async def handle_portfolio_button(message: Message) -> None:
    user_id = str(message.from_user.id)
    logger.info("Портфель запрошен пользователем %s", user_id)

    data = load_portfolio()
    user = data.get(user_id, {"balances": {}})
    balances: Dict[str, float] = user.get("balances", {})

    if not balances:
        await message.answer(
            "💼 У тебя ещё нет портфеля.\n\n"
            "Добавить монету:\n"
            "<code>+ BTC 0.01</code>\n"
            "Убрать часть монеты:\n"
            "<code>- BTC 0.005</code>\n\n"
            "Поддерживаются: BTC, ETH, USDT."
        )
        return

    symbols = list(balances.keys())
    prices = get_prices_for_symbols(symbols)

    total_usd = 0.0
    lines = ["<b>💼 Твой портфель</b>\n"]
    for sym, amount in balances.items():
        line = f"• {sym}: {amount:g}"
        if sym in prices:
            value = prices[sym] * amount
            total_usd += value
            line += f" ≈ {format_usd(value)}"
        lines.append(line)

    lines.append("\nИтого по известным монетам: <b>" + format_usd(total_usd) + "</b>")
    lines.append(
        "\nИзмени портфель с помощью сообщений:\n"
        "<code>+ BTC 0.01</code> — добавить\n"
        "<code>- BTC 0.01</code> — уменьшить\n"
        "Обмен: нажми «🔁 Обменять»."
    )

    await message.answer("\n".join(lines))


@dp.message(F.text == "🔁 Обменять")
async def handle_exchange_button(message: Message) -> None:
    await message.answer(
        "🔁 Обмен между монетами (BTC/ETH/USDT).\n\n"
        "Формат команды:\n"
        "<code>EX BTC USDT 0.01</code>\n"
        "— обменять 0.01 BTC в USDT по текущему курсу CoinGecko.\n\n"
        "Твои текущие монеты можно посмотреть через «💼 Мой портфель»."
    )


@dp.message(F.text == "🔔 Уведомления")
async def handle_alerts_toggle(message: Message) -> None:
    uid = message.from_user.id
    if uid in ALERT_ENABLED:
        ALERT_ENABLED.remove(uid)
        await message.answer("🔕 Авто-уведомления отключены.")
    else:
        ALERT_ENABLED.add(uid)
        await message.answer(
            f"🔔 Авто-уведомления включены.\n"
            f"Я буду следить за BTC и присылать сигнал,\n"
            f"если изменение за 24ч превысит ±{ALERT_THRESHOLD:.1f}%."
        )


@dp.message(F.text == "☎ Поддержка")
async def handle_support(message: Message) -> None:
    text = (
        "☎ Поддержка CryptoBay\n\n"
        "Пиши админу: @your_nick\n"
        "ID для связи: <code>{}</code>".format(message.from_user.id)
    )
    await message.answer(text)

# === Команды портфеля и обмена (текстовые) ===

@dp.message(F.text.regexp(r"^[\+\-]\s*[A-Za-z]{2,10}\s+[0-9\.,]+$"))
async def handle_portfolio_edit(message: Message) -> None:
    """
    + BTC 0.01
    - ETH 0.5
    """
    user_id = str(message.from_user.id)
    text = message.text.strip()
    sign = 1 if text.startswith("+") else -1

    try:
        _, sym, amount_str = text.replace("+", "", 1).replace("-", "", 1).split(maxsplit=2)
        sym = sym.upper()
        amount = float(amount_str.replace(",", "."))
    except Exception:
        await message.answer("⚠ Неверный формат. Пример: <code>+ BTC 0.01</code>")
        return

    if sym not in SYMBOL_TO_COINGECKO:
        await message.answer("⚠ Пока поддерживаются только BTC, ETH, USDT.")
        return

    if amount <= 0:
        await message.answer("⚠ Сумма должна быть больше 0.")
        return

    data = load_portfolio()
    user = data.get(user_id, {"balances": {}})
    balances: Dict[str, float] = user.get("balances", {})

    current = balances.get(sym, 0.0)
    new_amount = current + sign * amount

    if new_amount < 0:
        await message.answer("⚠ Нельзя уйти в минус по монете.")
        return
    if abs(new_amount) < 1e-10:
        balances.pop(sym, None)
    else:
        balances[sym] = new_amount

    user["balances"] = balances
    data[user_id] = user
    save_portfolio(data)

    await message.answer(f"✅ Портфель обновлён: {sym} = {new_amount:g}")
    await handle_portfolio_button(message)


@dp.message(F.text.regexp(r"^(EX|ex)\s+[A-Za-z]{2,10}\s+[A-Za-z]{2,10}\s+[0-9\.,]+$"))
async def handle_exchange(message: Message) -> None:
    """
    EX BTC USDT 0.01
    """
    user_id = str(message.from_user.id)
    parts = message.text.split()
    _, from_sym, to_sym, amount_str = parts
    from_sym = from_sym.upper()
    to_sym = to_sym.upper()
    amount = float(amount_str.replace(",", "."))

    if from_sym == to_sym:
        await message.answer("⚠ Нельзя обменять монету саму на себя.")
        return
    if from_sym not in SYMBOL_TO_COINGECKO or to_sym not in SYMBOL_TO_COINGECKO:
        await message.answer("⚠ Для обмена доступны только BTC, ETH, USDT.")
        return
    if amount <= 0:
        await message.answer("⚠ Сумма должна быть больше 0.")
        return

    data = load_portfolio()
    user = data.get(user_id, {"balances": {}})
    balances: Dict[str, float] = user.get("balances", {})

    have = balances.get(from_sym, 0.0)
    if have < amount:
        await message.answer(
            f"⚠ Недостаточно {from_sym}. Сейчас в портфеле: {have:g}"
        )
        return

    prices = get_prices_for_symbols([from_sym, to_sym])
    if from_sym not in prices or to_sym not in prices:
        await message.answer("⚠ Не удалось получить цены для обмена. Попробуй позже.")
        return

    usd_value = prices[from_sym] * amount
    to_amount = usd_value / prices[to_sym]

    balances[from_sym] = have - amount
    if balances[from_sym] <= 0:
        balances.pop(from_sym, None)
    balances[to_sym] = balances.get(to_sym, 0.0) + to_amount

    user["balances"] = balances
    data[user_id] = user
    save_portfolio(data)

    await message.answer(
        "✅ Обмен выполнен.\n"
        f"{amount:g} {from_sym} → {to_amount:.6f} {to_sym}\n"
        f"Курс: 1 {from_sym} ≈ {prices[from_sym] / prices[to_sym]:.5f} {to_sym}"
    )
    await handle_portfolio_button(message)


@dp.message(F.text)
async def fallback_menu(message: Message) -> None:
    # Если пользователь пишет что-то своё — подсказываем про меню
    await message.answer("Выбери действие на клавиатуре ниже 👇", reply_markup=main_keyboard())

# === Фоновый наблюдатель за ценой BTC ===

async def price_watcher() -> None:
    """
    Раз в 5 минут смотрим 24h % BTC и при сильных движениях шлём сигнал тем,
    кто включил авто-уведомления.
    """
    logger.info("Запуск фонового наблюдателя цен")
    last_state: Dict[int, str] = {}  # user_id -> 'up' | 'down' | 'normal'

    while True:
        try:
            if ALERT_ENABLED:
                btc = get_btc_overview()
                if btc and btc.get("change_24h") is not None:
                    change = float(btc["change_24h"])
                    state = "normal"
                    if change >= ALERT_THRESHOLD:
                        state = "up"
                    elif change <= -ALERT_THRESHOLD:
                        state = "down"

                    for uid in list(ALERT_ENABLED):
                        prev = last_state.get(uid)
                        if state != "normal" and state != prev:
                            arrow = "🚀" if state == "up" else "📉"
                            sign_text = "вырос" if state == "up" else "упал"
                            try:
                                await bot.send_message(
                                    uid,
                                    f"{arrow} BTC {sign_text} на {change:+.2f}% за 24ч.\n"
                                    f"Текущая цена ≈ {format_usd(btc['price'])}",
                                )
                            except Exception as e:
                                logger.error("Ошибка отправки алерта пользователю %s: %s", uid, e)
                        last_state[uid] = state
            await asyncio.sleep(300)  # 5 минут
        except Exception as e:
            logger.error("Ошибка в price_watcher: %s", e)
            await asyncio.sleep(60)

# === Точка входа ===

async def main() -> None:
    watcher_task = asyncio.create_task(price_watcher())
    try:
        await dp.start_polling(bot)
    finally:
        watcher_task.cancel()

if __name__ == "__main__":
    asyncio.run(main())
