import os
import re
import tempfile
import requests
import pymysql
import instaloader
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# --- Konfiguratsiya (environment variables dan oling) ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")  # Telegram bot token
DB_HOST = os.environ.get("DB_HOST", "telegrambotsmorphius.mysql.pythonanywhere-services.com")
DB_USER = os.environ.get("DB_USER")
DB_PASS = os.environ.get("DB_PASS")
DB_NAME = os.environ.get("DB_NAME")

if not BOT_TOKEN or not DB_USER or not DB_PASS or not DB_NAME:
    raise SystemExit("Iltimos, BOT_TOKEN, DB_USER, DB_PASS, DB_NAME muhit o'zgaruvchilarini o'rnating.")

# --- Helper: MySQLga ulanish ---
def insert_download_record(tg_user_id, tg_username, instagram_url, filename):
    conn = pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, database=DB_NAME,
                           charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            sql = "INSERT INTO downloads (tg_user_id, tg_username, instagram_url, filename) VALUES (%s, %s, %s, %s)"
            cur.execute(sql, (tg_user_id, tg_username, instagram_url, filename))
        conn.commit()
    finally:
        conn.close()

# --- Helper: shortcode olish ---
INSTAGRAM_URL_RE = re.compile(r"(?:/p/|/tv/|/reel/|/reels/|/tv/|/v/)([A-Za-z0-9_-]+)")

def extract_shortcode(url: str):
    # bir nechta formatlarni qoplaydi
    m = INSTAGRAM_URL_RE.search(url)
    if m:
        return m.group(1)
    # ba'zan URL oxirida shortcode bo'ladi
    parts = url.rstrip("/").split("/")
    if parts:
        return parts[-1]
    return None

# --- Instagram dan video URL olish ---
L = instaloader.Instaloader(download_pictures=False,
                            download_videos=False,
                            save_metadata=False,
                            compress_json=False,
                            post_metadata_txt_pattern='')

async def fetch_instagram_video_url(shortcode: str):
    try:
        post = instaloader.Post.from_shortcode(L.context, shortcode)
        if post.is_video:
            return post.video_url
        # agar carousel bo'lsa: topilgan birinchi videoni qaytarish
        for node in post.get_sidecar_nodes():
            if node.is_video:
                return node.video_url
    except Exception as e:
        # xatolik (masalan: private post yoki shortcode xato)
        return None
    return None

# --- Bot handlerlari ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Salom! Instagram video linkini yuboring — men uni yuklab, qaytaraman. (Faqat public postlar uchun)")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Instagram post yoki reel linkini yuboring, men video faylini qaytaraman va bazaga yozaman.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_user = update.effective_user
    # URL ekanligini oddiy tekshiruv
    if "instagram.com" not in text:
        await update.message.reply_text("Iltimos, Instagram post yoki reel linkini yuboring (masalan: https://www.instagram.com/reel/SHORTCODE/).")
        return

    await update.message.reply_text("Link qabul qilindi. Yuklab olinmoqda... (agar public bo'lsa)")

    shortcode = extract_shortcode(text)
    if not shortcode:
        await update.message.reply_text("Shortcode topilmadi. Iltimos to'liq Instagram post/reel URL yuboring.")
        return

    video_url = await fetch_instagram_video_url(shortcode)
    if not video_url:
        await update.message.reply_text("Video topilmadi yoki post private/olmadi. Iltimos, post ommaviy ekanligini tekshiring.")
        return

    # Video'ni yuklab olish va Telegramga yuborish
    try:
        # vaqtinchalik fayl
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmpf:
            resp = requests.get(video_url, stream=True, timeout=30)
            resp.raise_for_status()
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    tmpf.write(chunk)
            tmp_filename = tmpf.name

        # Telegramga yuborish
        with open(tmp_filename, "rb") as video_file:
            await update.message.reply_video(video=video_file, timeout=120)

        # Bazaga yozuv qoldirish
        insert_download_record(
            tg_user_id=chat_user.id,
            tg_username=chat_user.username or chat_user.full_name,
            instagram_url=text,
            filename=os.path.basename(tmp_filename)
        )

        await update.message.reply_text("Yuklandi va bazaga yozildi ✅")
    except Exception as e:
        await update.message.reply_text(f"Xatolik yuz berdi: {e}")
    finally:
        try:
            if 'tmp_filename' in locals() and os.path.exists(tmp_filename):
                os.remove(tmp_filename)
        except Exception:
            pass

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("Bot ishga tushmoqda...")
    app.run_polling()

if __name__ == "__main__":
    main()
