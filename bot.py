"""
Telegram Business Bot — تحويل العملات في المحادثات الخاصة
ملف واحد فقط. كل حاجة جواه.
"""
import re
import logging
import httpx
from cachetools import TTLCache
from telegram import Update
from telegram.ext import Application, BusinessMessageHandler, ContextTypes

# ============================================================
# ⚙️ الإعدادات — عدّل هنا
# ============================================================
BOT_TOKEN = "8557993863:AAFrUKaWNoFOaiNdjyT6PsDy390umkBl5FE"

# مصدر سعر الدولار في مصر (اختياري)
# سجل مجاناً على https://app.exchangerate-api.com/sign-up
EXCHANGE_RATE_API_KEY = "https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd,egp"  # سيبها فاضية لو مش عايز

COINGECKO = "https://api.coingecko.com/api/v3"
EXCHANGE_API = "https://v6.exchangerate-api.com/v6"

# ============================================================
# Logging
# ============================================================
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Cache للأسعار (5 دقايق)
price_cache = TTLCache(maxsize=50, ttl=300)


# ============================================================
# Parser
# ============================================================
def parse_message(text: str):
    if not text:
        return None

    cleaned = text.strip().replace(",", "")
    pattern = r"^([\d٠-٩.]+)\s*(تون|ton|usdt|دولار|جنيه|جنية|ج|egp|\$)?$"
    match = re.match(pattern, cleaned, re.IGNORECASE)
    if not match:
        return None

    # تحويل الأرقام العربية
    arabic_digits = "٠١٢٣٤٥٦٧٨٩"
    raw_num = match.group(1)
    for i, d in enumerate(arabic_digits):
        raw_num = raw_num.replace(d, str(i))

    try:
        amount = float(raw_num)
    except ValueError:
        return None

    if amount <= 0:
        return None

    currency_raw = (match.group(2) or "").lower()

    if currency_raw in ["تون", "ton"]:
        currency = "TON"
    elif currency_raw in ["usdt", "$", "دولار"]:
        currency = "USDT"
    elif currency_raw in ["جنيه", "جنية", "ج", "egp"]:
        currency = "EGP"
    elif currency_raw == "":
        currency = "USDT"
    else:
        return None

    return {"amount": amount, "currency": currency}


# ============================================================
# Prices
# ============================================================
async def _fetch_ton():
    if "ton" in price_cache:
        return price_cache["ton"]
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(
            f"{COINGECKO}/simple/price",
            params={"ids": "the-open-network", "vs_currencies": "usd,egp"},
        )
        r.raise_for_status()
        d = r.json()["the-open-network"]
        result = {"usd": d["usd"], "egp": d["egp"]}
        price_cache["ton"] = result
        return result


async def _fetch_usdt():
    if "usdt" in price_cache:
        return price_cache["usdt"]
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(
            f"{COINGECKO}/simple/price",
            params={"ids": "tether", "vs_currencies": "usd,egp"},
        )
        r.raise_for_status()
        d = r.json()["tether"]
        result = {"usd": d["usd"], "egp": d["egp"]}
        price_cache["usdt"] = result
        return result


async def _fetch_usd_egp():
    if "usd_egp" in price_cache:
        return price_cache["usd_egp"]

    if EXCHANGE_RATE_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(
                    f"{EXCHANGE_API}/{EXCHANGE_RATE_API_KEY}/pair/USD/EGP"
                )
                r.raise_for_status()
                rate = r.json()["conversion_rate"]
                price_cache["usd_egp"] = rate
                return rate
        except Exception as e:
            logger.warning(f"[Exchange] {e}")

    fallback = 48.5
    price_cache["usd_egp"] = fallback
    return fallback


async def fetch_all_prices():
    ton = await _fetch_ton()
    usdt = await _fetch_usdt()
    usd_egp = await _fetch_usd_egp()
    return {
        "ton_usd": ton["usd"],
        "ton_egp": ton["egp"],
        "usdt_usd": usdt["usd"],
        "usdt_egp": usdt["egp"],
        "usd_egp": usd_egp,
    }


# ============================================================
# Formatter
# ============================================================
def format_reply(amount, currency, p):
    label = {"EGP": "جنيه", "TON": "تون", "USDT": "$"}[currency]
    lines = [f"{amount:g} {label}", ""]

    if currency == "TON":
        usd = amount * p["ton_usd"]
        egp = amount * p["ton_egp"]
        usdt = usd / p["usdt_usd"]
        lines += [
            f"↗️ {amount:g} TON 💎",
            f"↗️ {usdt:.2f} USDT 💵",
            f"↗️ {usd:.2f} USD 💵",
            f"↗️ {egp:.2f} EGP 🇪🇬",
        ]
    elif currency == "USDT":
        egp = amount * p["usdt_egp"]
        ton = amount / p["ton_usd"]
        lines += [
            f"↗️ {amount:g} USDT 💵",
            f"↗️ {egp:.2f} EGP 🇪🇬",
            f"↗️ {ton:.4f} TON 💎",
        ]
    elif currency == "EGP":
        usd = amount / p["usd_egp"]
        ton = usd / p["ton_usd"]
        usdt = usd / p["usdt_usd"]
        lines += [
            f"↗️ {amount:g} EGP 🇪🇬",
            f"↗️ {usd:.2f} USD 💵",
            f"↗️ {usdt:.2f} USDT 💵",
            f"↗️ {ton:.4f} TON 💎",
        ]

    return "\n".join(lines)


# ============================================================
# Handler
# ============================================================
async def handle_business(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.business_message
    if not msg or not msg.text:
        return

    if msg.from_user and msg.from_user.id == context.bot.id:
        return

    parsed = parse_message(msg.text)
    if not parsed:
        return

    try:
        # امسح رسالة الطرف التاني
        try:
            await context.bot.delete_business_message(
                business_connection_id=msg.business_connection_id,
                chat_id=msg.chat.id,
                message_id=msg.message_id,
            )
        except Exception as e:
            logger.warning(f"[Delete Failed] {e}")

        # جيب الأسعار وابعت الرد
        prices = await fetch_all_prices()
        reply = format_reply(parsed["amount"], parsed["currency"], prices)

        await context.bot.send_message(
            chat_id=msg.chat.id,
            text=reply,
            business_connection_id=msg.business_connection_id,
        )

    except Exception as e:
        logger.error(f"[Business Handler] {e}")


# ============================================================
# Main
# ============================================================
def main():
    if not BOT_TOKEN or BOT_TOKEN == "ضع_التوكن_هنا":
        raise SystemExit("❌ ضع BOT_TOKEN في أول الملف")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(BusinessMessageHandler(handle_business))

    logger.info("🚀 البوت شغال...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()