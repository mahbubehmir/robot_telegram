import subprocess
import librosa
import noisereduce as nr
import soundfile as sf
from pydub import AudioSegment
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import os
import whisper
import json
import logging
from deep_translator import GoogleTranslator

# تنظیمات پیشرفته
TOKEN ="7910879682:AAFxRfyd9iCkzZToP496s8PlGTwFJhDbj88"
#TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TEMP_FILES = [
    "input_video.mp4", "extracted_audio.mp3",
    "cleaned_audio.wav", "final_audio.wav",
    "transcribed_text_whisper.json", "transcribed_text_whisper.txt",
    "subtitles_editable.txt", "edited_subtitles.txt",
    "final_subtitles.srt", "output_with_subtitles.mp4"
]

class Config:
    MODEL_SIZE = "small"
    MAX_VIDEO_SIZE = 50 * 1024 * 1024  # 50MB

config = Config()

# تنظیمات لاگینگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ------------------- توابع کمکی -------------------
def cleanup_files():
    """پاکسازی فایل های موقت"""
    for file in TEMP_FILES:
        try:
            if os.path.exists(file):
                os.remove(file)
                logger.info(f"پاکسازی: {file}")
        except Exception as e:
            logger.error(f"خطا در پاکسازی {file}: {str(e)}")

def format_time(seconds: float) -> str:
    """فرمت دهی زمان برای زیرنویس"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = seconds % 60
    milliseconds = int((seconds - int(seconds)) * 1000)
    return f"{hours:02}:{minutes:02}:{int(seconds):02},{milliseconds:03}"

# ------------------- توابع پردازش -------------------
def create_editable_txt(transcription_result: dict) -> None:
    """ایجاد فایل متنی قابل ویرایش با فرمت ساده"""
    try:
        with open("subtitles_editable.txt", "w", encoding="utf-8") as f:
            for seg in transcription_result["segments"]:
                start = format_time(seg["start"])
                end = format_time(seg["end"])
                text = seg["text"].replace("\n", " ")
                translated = GoogleTranslator(source='auto', target='fa').translate(text)
                
                f.write(f"{start} | {end} | {text} | {translated}\n")
        
        logger.info("فایل متنی قابل ویرایش ایجاد شد")
        
    except Exception as e:
        logger.error(f"خطا در ایجاد فایل متنی: {str(e)}")
        raise

def txt_to_srt(input_txt: str, output_srt: str) -> None:
    """تبدیل فایل متنی ویرایش شده به فرمت SRT"""
    try:
        with open(input_txt, "r", encoding="utf-8") as fin:
            lines = fin.readlines()
        
        with open(output_srt, "w", encoding="utf-8") as fout:
            for i, line in enumerate(lines):
                parts = line.strip().split("|")
                if len(parts) != 4:
                    raise ValueError("فرمت فایل نامعتبر است")
                
                start, end, text, translated = [part.strip() for part in parts]
                
                fout.write(f"{i+1}\n")
                fout.write(f"{start} --> {end}\n")
                fout.write(f"{text}\n{translated}\n\n")
        
        logger.info("تبدیل به SRT انجام شد")
        
    except Exception as e:
        logger.error(f"خطا در تبدیل به SRT: {str(e)}")
        raise

# ------------------- هندلرهای ربات -------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ارسال راهنمای کامل"""
    help_text = (
        " ربات تولید زیرنویس دوزبانه\n\n"
        "1. ویدیو را ارسال کنید (حداکثر 50MB)\n"
        "2. فایل متنی را ویرایش کنید\n"
        "3. فایل ویرایش شده را بازگردانید\n"
        "4. ویدیو نهایی را دریافت کنید\n\n"
        " فرمت فایل متنی:\n"
        "شروع | پایان | متن انگلیسی | متن فارسی"
    )
    await update.message.reply_text(help_text)

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پردازش ویدیوی ورودی"""
    try:
        cleanup_files()
        
        # بررسی حجم ویدیو
        if update.message.video.file_size > config.MAX_VIDEO_SIZE:
            await update.message.reply_text(" حجم ویدیو باید کمتر از 50 مگابایت باشد")
            return

        # دریافت ویدیو
        video_file = await update.message.video.get_file()
        await video_file.download_to_drive("input_video.mp4")
        await update.message.reply_text(" در حال پردازش ویدیو...")

        # استخراج و پردازش صدا
        subprocess.run([
            'ffmpeg', '-i', 'input_video.mp4',
            '-q:a', '0', '-map', 'a', 'extracted_audio.mp3'
        ], check=True)
        
        # کاهش نویز
        y, sr = librosa.load("extracted_audio.mp3", sr=None)
        reduced_audio = nr.reduce_noise(y=y, sr=sr)
        sf.write("cleaned_audio.wav", reduced_audio, sr)
        
        # تشخیص گفتار
        model = whisper.load_model(config.MODEL_SIZE).cpu()
        result = model.transcribe("cleaned_audio.wav")
        
        # ایجاد فایل متنی قابل ویرایش
        create_editable_txt(result)
        
        # ارسال فایل برای ویرایش
        await update.message.reply_document(
            document=open("subtitles_editable.txt", "rb"),
            caption=(
                " فایل زیرنویس برای ویرایش:\n"
                "1. فرمت را تغییر ندهید\n"
                "2. متنها را اصلاح کنید\n"
                "3. فایل ویرایش شده را ارسال کنید"
            )
        )

    except Exception as e:
        logger.error(f"خطای پردازش ویدیو: {str(e)}")
        await update.message.reply_text(" خطا در پردازش ویدیو")
        cleanup_files()

async def handle_text_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پردازش فایل متنی ویرایش شده"""
    try:
        if not update.message.document.file_name.endswith('.txt'):
            await update.message.reply_text(" لطفا فقط فایل TXT ارسال کنید")
            return

        # دریافت فایل ویرایش شده
        txt_file = await update.message.document.get_file()
        await txt_file.download_to_drive("edited_subtitles.txt")
        await update.message.reply_text(" در حال تولید ویدیو نهایی...")

        # تبدیل به SRT
        txt_to_srt("edited_subtitles.txt", "final_subtitles.srt")

        # اضافه کردن زیرنویس به ویدیو
        subprocess.run([
            'ffmpeg', '-i', 'input_video.mp4',
            '-vf', "subtitles=final_subtitles.srt:force_style='FontName=Arial,Fontsize=24'",
            '-c:v', 'libx264', '-crf', '23', '-preset', 'medium',
            '-c:a', 'copy', 'output_with_subtitles.mp4'
        ], check=True)

        # ارسال ویدیوی نهایی
        await update.message.reply_video(
            video=open("output_with_subtitles.mp4", "rb"),
            caption=" ویدیو نهایی با زیرنویس ویرایش شده"
        )

    except Exception as e:
        logger.error(f"خطای پردازش فایل متنی: {str(e)}")
        await update.message.reply_text(" خطا در پردازش فایل ویرایش شده")
    finally:
        cleanup_files()

# ------------------- راه اندازی ربات -------------------
def main() -> None:
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.Document.TXT, handle_text_file))
    
    logger.info("ربات در حال اجرا است...")
    app.run_polling()

if __name__ == "__main__":
    main()
