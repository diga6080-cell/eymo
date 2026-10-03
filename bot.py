# -*- coding: utf-8 -*-
"""
Telegram Emoji -> HTML / Python Code Bot
- يستقبل إيموجي مميز (Premium / Custom Emoji) أو نص عادي
- يحوّله لكود HTML جاهز
- يحوّله لكود Python جاهز
- يدعم النسخ كنص
"""

import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MessageEntity,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ================== الإعدادات ==================
TOKEN = "8881896681:AAEGqXmDlIoVAyXnIxAOxLGFLYhzBErD6ro"   # <<< عدّل هذا فقط

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# مخزن مؤقت لكل مستخدم: {user_id: {"text": ..., "entities": ...}}
USER_CACHE: dict[int, dict] = {}


# ================== أدوات التحويل ==================

def escape_html(text: str) -> str:
    """تهريب الرموز الخاصة بـ HTML"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def escape_py_string(text: str) -> str:
    """تهريب النص ليكون صالح داخل سلسلة Python"""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def build_html(text: str, entities: list[MessageEntity]) -> str:
    """
    بناء كود HTML من النص + الكيانات.
    يدعم:
      - custom_emoji (الإيموجي المميز)
      - bold, italic, underline, strikethrough, spoiler
      - code, pre
      - text_link
    """
    if not text:
        return ""

    # ترتيب الكيانات حسب الموقع ثم الأطول أولًا
    ents = sorted(entities, key=lambda e: (e.offset, -e.length))

    # تحويل النص إلى قائمة أحرف لتسهيل الإدراج
    # (نستخدم UTF-16 code units لأن تيليجرام يعتمد عليها)
    utf16 = text.encode("utf-16-le")
    total_units = len(utf16) // 2

    # قائمة ناتجة بترتيب المواقع (نُدرج وسوم الفتح/الإغلاق)
    open_tags: dict[int, list[str]] = {}
    close_tags: dict[int, list[str]] = {}

    for e in ents:
        start = e.offset
        end = e.offset + e.length

        tag_open = ""
        tag_close = ""

        if e.type == "bold":
            tag_open, tag_close = "<b>", "</b>"
        elif e.type == "italic":
            tag_open, tag_close = "<i>", "</i>"
        elif e.type == "underline":
            tag_open, tag_close = "<u>", "</u>"
        elif e.type == "strikethrough":
            tag_open, tag_close = "<s>", "</s>"
        elif e.type == "spoiler":
            tag_open, tag_close = "<tg-spoiler>", "</tg-spoiler>"
        elif e.type == "code":
            tag_open, tag_close = "<code>", "</code>"
        elif e.type == "pre":
            lang = (e.language or "") if hasattr(e, "language") else ""
            if lang:
                tag_open = f'<pre><code class="language-{lang}">'
            else:
                tag_open = "<pre>"
            tag_close = "</code></pre>"
        elif e.type == "text_link":
            url = e.url or ""
            tag_open = f'<a href="{url}">'
            tag_close = "</a>"
        elif e.type == "custom_emoji":
            # الإيموجي المميز: نستخرج الـ custom_emoji_id
            emoji_id = getattr(e, "custom_emoji_id", None)
            tag_open = f'<tg-emoji emoji-id="{emoji_id}">'
            tag_close = "</tg-emoji>"
        else:
            continue

        open_tags.setdefault(start, []).append(tag_open)
        close_tags.setdefault(end, []).append(tag_close)

    # نبني النص النهائي بالتنقل حرفًا بحرف (unit by unit في UTF-16)
    out_parts = []
    i = 0
    while i <= total_units:
        # إغلاق الوسوم عند هذا الموقع (بترتيب عكسي للإدراج)
        if i in close_tags:
            for t in reversed(close_tags[i]):
                out_parts.append(t)
        # فتح الوسوم عند هذا الموقع
        if i in open_tags:
            for t in open_tags[i]:
                out_parts.append(t)

        if i < total_units:
            # استخرج وحدة UTF-16 واحدة
            char_unit = utf16[i * 2 : i * 2 + 2]
            try:
                ch = char_unit.decode("utf-16-le")
            except UnicodeDecodeError:
                ch = ""
            # نهرب الرموز الخاصة
            out_parts.append(escape_html(ch))
        i += 1

    return "".join(out_parts)


def build_python(text: str, entities: list[MessageEntity]) -> str:
    """
    بناء كود Python من النص + الكيانات.
    يُنتج تعليمات واضحة قابلة للاستخدام مع python-telegram-bot.
    """
    lines = []
    lines.append("# -*- coding: utf-8 -*-")
    lines.append('"""')
    lines.append("كود Python جاهز لإرسال الرسالة مع الإيموجي المميز / التنسيقات")
    lines.append("يتطلب: pip install python-telegram-bot")
    lines.append('"""')
    lines.append("")
    lines.append("from telegram import MessageEntity, Bot")
    lines.append("")
    lines.append("TOKEN = \"ضع_التوكن_هنا\"")
    lines.append("CHAT_ID = 123456789  # ضع معرف المحادثة هنا")
    lines.append("")
    lines.append("TEXT = (")
    # نقسم النص على أسطر للحفاظ على القراءة
    safe_text = escape_py_string(text)
    # نقسم إلى أسطر إذا كان طويلًا
    chunk_size = 80
    if len(safe_text) <= chunk_size:
        lines.append(f'    "{safe_text}"')
    else:
        for i in range(0, len(safe_text), chunk_size):
            chunk = safe_text[i : i + chunk_size]
            lines.append(f'    "{chunk}"')
    lines.append(")")
    lines.append("")
    lines.append("ENTITIES = [")

    for e in entities:
        etype = e.type
        if etype == "custom_emoji":
            emoji_id = getattr(e, "custom_emoji_id", None)
            lines.append(
                f'    MessageEntity(type=MessageEntity.CUSTOM_EMOJI, '
                f'offset={e.offset}, length={e.length}, '
                f'custom_emoji_id="{emoji_id}"),'
            )
        elif etype == "text_link":
            lines.append(
                f'    MessageEntity(type=MessageEntity.TEXT_LINK, '
                f'offset={e.offset}, length={e.length}, url="{e.url}"),'
            )
        elif etype == "pre":
            lang = (e.language or "") if hasattr(e, "language") else ""
            lines.append(
                f'    MessageEntity(type=MessageEntity.PRE, '
                f'offset={e.offset}, length={e.length}, language="{lang}"),'
            )
        else:
            lines.append(
                f'    MessageEntity(type=MessageEntity.{etype.upper()}, '
                f'offset={e.offset}, length={e.length}),'
            )

    lines.append("]")
    lines.append("")
    lines.append("")
    lines.append("async def send():")
    lines.append("    bot = Bot(token=TOKEN)")
    lines.append("    await bot.send_message(")
    lines.append("        chat_id=CHAT_ID,")
    lines.append("        text=TEXT,")
    lines.append("        entities=ENTITIES,")
    lines.append("    )")
    lines.append("")
    lines.append("")
    lines.append('if __name__ == "__main__":')
    lines.append("    import asyncio")
    lines.append("    asyncio.run(send())")

    return "\n".join(lines)


# ================== هاندلرز البوت ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 أهلاً بك في بوت تحويل الإيموجي المميز\n\n"
        "📌 أرسل لي أي رسالة تحتوي على:\n"
        "• إيموجي مميز (Premium Emoji)\n"
        "• تنسيقات (Bold / Italic / Spoiler...)\n\n"
        "وسأحوّلها فورًا إلى:\n"
        "🧩 كود HTML\n"
        "🐍 كود Python\n\n"
        "ثم اختر الصيغة التي تريدها من الأزرار."
    )
    await update.message.reply_text(text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not msg or not msg.text:
        await msg.reply_text("⚠️ الرجاء إرسال نص.")
        return

    text = msg.text
    entities = msg.entities or []

    if not entities:
        await msg.reply_text(
            "ℹ️ لم أجد أي إيموجي مميز أو تنسيق في رسالتك.\n"
            "أرسل رسالة تحتوي على إيموجي بريميوم أو Bold/Italic... إلخ."
        )
        return

    # تخزين مؤقت
    USER_CACHE[update.effective_user.id] = {"text": text, "entities": entities}

    # عرض أزرار الاختيار
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🧩 HTML", callback_data="fmt_html"),
                InlineKeyboardButton("🐍 Python", callback_data="fmt_py"),
            ],
            [
                InlineKeyboardButton("📋 كلاهما", callback_data="fmt_both"),
            ],
        ]
    )
    await msg.reply_text(
        "✅ تم استلام الرسالة.\nاختر صيغة التحويل:",
        reply_markup=keyboard,
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = USER_CACHE.get(user_id)
    if not data:
        await query.edit_message_text("⚠️ انتهت صلاحية البيانات. أعد إرسال الرسالة.")
        return

    text = data["text"]
    entities = data["entities"]
    choice = query.data

    try:
        if choice == "fmt_html":
            code = build_html(text, entities)
            header = "🧩 <b>كود HTML:</b>\n\n"
            await send_code(query, header, code, "html")

        elif choice == "fmt_py":
            code = build_python(text, entities)
            header = "🐍 <b>كود Python:</b>\n\n"
            await send_code(query, header, code, "python")

        elif choice == "fmt_both":
            html_code = build_html(text, entities)
            py_code = build_python(text, entities)

            await query.edit_message_text(
                "🧩 <b>كود HTML:</b>\n\n<pre>"
                + escape_html(html_code)
                + "</pre>",
                parse_mode=ParseMode.HTML,
            )
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="🐍 <b>كود Python:</b>\n\n<pre>"
                + escape_html(py_code)
                + "</pre>",
                parse_mode=ParseMode.HTML,
            )
    except Exception as e:
        logger.exception("خطأ أثناء التحويل")
        await query.message.reply_text(f"❌ حدث خطأ: {e}")


async def send_code(query, header: str, code: str, lang: str) -> None:
    """يرسل الكود داخل بلوك <pre> حتى يُنسخ بسهولة"""
    # حد تيليجرام للحروف 4096 — نقسم إذا لزم
    safe = escape_html(code)
    full = header + "<pre>" + safe + "</pre>"

    if len(full) <= 4000:
        await query.edit_message_text(full, parse_mode=ParseMode.HTML)
    else:
        # نقسم إلى رسائل
        await query.edit_message_text(header, parse_mode=ParseMode.HTML)
        chunk_size = 3500
        for i in range(0, len(safe), chunk_size):
            chunk = safe[i : i + chunk_size]
            await query.message.reply_text(
                "<pre>" + chunk + "</pre>", parse_mode=ParseMode.HTML
            )


# ================== التشغيل ==================

def main() -> None:
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🤖 البوت يعمل الآن...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()