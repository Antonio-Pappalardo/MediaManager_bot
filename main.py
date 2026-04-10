import os
import io
import asyncio
import logging
import imagehash
from PIL import Image
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.exceptions import TelegramBadRequest
import database

logging.basicConfig(level=logging.INFO)

load_dotenv()
TOKEN = str(os.getenv("TOKEN"))
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ==========================================
# /START COMMAND HANDLER
# ==========================================
@dp.message(CommandStart())
async def start_command(message: types.Message):
    if message.from_user and message.from_user.id == ADMIN_ID:
        await message.reply("Bot is online! Use /commands to see available actions.")

# ==========================================
# /LIST COMMAND HANDLER
# ==========================================
@dp.message(Command("list"))
async def list_command(message: types.Message):
    if message.from_user and message.from_user.id == ADMIN_ID:
        authorized_groups = await database.get_authorized_groups()
        if not authorized_groups:
            await message.reply("📭 No authorized groups at the moment.")
            return
        
        text = "📋 **Authorized Groups List:**\n\n"
        for group_id, group_name in authorized_groups:
            name = group_name if group_name else "Unknown Name"
            text += f"🔹 {name}\nID: `{group_id}`\n\n"
        await message.reply(text, parse_mode="Markdown")

# ==========================================
# /AUTHORIZE COMMAND HANDLER
# ==========================================
@dp.message(Command("authorize"))
async def authorize_command(message: types.Message, command: CommandObject):
    if message.from_user and message.from_user.id == ADMIN_ID:
        target_id = command.args.strip() if command.args else str(message.chat.id)
        name = (message.chat.title or "Unnamed Group") if not command.args else "Added via ID (Remote)"
        
        await database.authorize_group(target_id, name)
        await message.reply("✅ Group authorized successfully.")

# ==========================================
# /REVOKE COMMAND HANDLER
# ==========================================
@dp.message(Command("revoke"))
async def revoke_command(message: types.Message, command: CommandObject):
    if message.from_user and message.from_user.id == ADMIN_ID:
        target_id = command.args.strip() if command.args else str(message.chat.id)
        
        await database.revoke_group(target_id)
        await message.reply("⛔ Permission revoked.")
        
        try:
            await bot.leave_chat(target_id)
        except Exception:
            pass

# ==========================================
# /COMMANDS COMMAND HANDLER
# ==========================================
@dp.message(Command("commands"))
async def commands_command(message: types.Message):
    # Only reply in private chat to the admin
    if message.chat.type == "private" and message.from_user and message.from_user.id == ADMIN_ID:
        text = (
            "🛠️ **CONTROL PANEL**\n\n"
            "Available commands:\n\n"
            "🔹 `/start` - Check bot status.\n"
            "🔹 `/list` - Show authorized groups and their IDs.\n"
            "🔹 `/commands` - Show this help message.\n\n"
            "🔹 `/authorize` - (In group) Authorize the bot for the current group.\n"
            "🔹 `/authorize [ID]` - (In private) Authorize a group remotely.\n"
            "🔹 `/revoke` - (In group) Revoke permission and make the bot leave.\n"
            "🔹 `/revoke [ID]` - (In private) Revoke permission remotely."
        )
        await message.reply(text, parse_mode="Markdown")

# ==========================================
# MEDIA HANDLER (DUPLICATE DETECTION)
# ==========================================
@dp.message(F.photo | F.video)
async def handle_media(message: types.Message, bot: Bot):
    group_id = str(message.chat.id)

    # Check permissions and update group name if necessary
    saved_group_name = await database.check_permission_and_name(group_id)
    
    if saved_group_name is None:
        return

    current_name = message.chat.title or "Private Chat"
    
    if saved_group_name != current_name:
        await database.authorize_group(group_id, current_name)
        logging.info(f"🔄 Group name updated in DB: {current_name}")

    message_id = message.message_id
    duplicate_found = False
    original_message_id = None

    # --- PHOTO HANDLING ---
    if message.photo:
        try:
            photo = message.photo[-1]
            telegram_unique_id = photo.file_unique_id
            
            # Fast check using Telegram's unique ID
            fast_check_result = await database.check_id(group_id, telegram_unique_id)
            
            if fast_check_result:
                duplicate_found = True
                original_message_id = fast_check_result
                logging.info("Duplicate found via Telegram ID")
            else:
                logging.info("New ID, downloading image for Hash check...")
                memory_file = io.BytesIO()
                await bot.download(photo, destination=memory_file)
                memory_file.seek(0)
                
                image = Image.open(memory_file)
                current_hash = str(imagehash.phash(image))

                # Slow check using perceptual hash
                slow_check_result = await database.check_hash(group_id, current_hash, 'photo')
                
                if slow_check_result:
                    duplicate_found = True
                    original_message_id = slow_check_result
                    logging.info("Duplicate found via pHash")
                else:
                    await database.add_to_database(group_id, 'photo', telegram_unique_id, current_hash, message_id)

        except Exception as e:
            logging.error(f"Error processing photo: {e}")

    # --- VIDEO HANDLING ---
    elif message.video:
        try:
            telegram_unique_id = message.video.file_unique_id
            fast_check_result = await database.check_id(group_id, telegram_unique_id)
            
            if fast_check_result:
                duplicate_found = True
                original_message_id = fast_check_result
                logging.info("Video duplicate found via Telegram ID")
            
            elif message.video.thumbnail:
                logging.info("New video ID, analyzing thumbnail...")
                thumbnail = message.video.thumbnail
                memory_file = io.BytesIO()
                await bot.download(thumbnail, destination=memory_file)
                memory_file.seek(0)
                
                image = Image.open(memory_file)
                current_hash = str(imagehash.phash(image))

                slow_check_result = await database.check_hash(group_id, current_hash, 'video')
                
                if slow_check_result:
                    duplicate_found = True
                    original_message_id = slow_check_result
                    logging.info("Video duplicate found via Thumbnail pHash")
                else:
                    await database.add_to_database(group_id, 'video', telegram_unique_id, current_hash, message_id)
            else:
                logging.info("Video without thumbnail, saving only ID to database.")
                await database.add_to_database(group_id, 'video', telegram_unique_id, "", message_id)
        except Exception as e:
            logging.error(f"Error processing video: {e}")


    # ==========================================
    # FINAL RESPONSE AND ERROR HANDLING
    # ==========================================
    if duplicate_found and original_message_id is not None:
        try:
            await message.answer(
                "⚠️ *Warning!* This file is a duplicate.\nHere is the original post 👇",
                reply_parameters=types.ReplyParameters(
                    message_id=original_message_id,
                    allow_sending_without_reply=False
                ),
                parse_mode="Markdown",
                disable_notification=True
            )
        
        except TelegramBadRequest as e:
            if "message to reply not found" in str(e).lower() or "message not found" in str(e).lower() or "reply message not found" in str(e).lower():
                logging.info(f"Original post {original_message_id} was deleted. Promoting new post as original.")
                await database.update_original_message(group_id, original_message_id, message_id)
            else:
                logging.error(f"Telegram error during reply: {e}")
                
        except Exception as e:
            logging.error(f"Unable to send warning message: {e}")

# ==========================================
# MAIN FUNCTION
# ==========================================
async def main():
    print("Bot is starting...")
    await database.initialize_database()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())