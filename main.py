import os
import io
import asyncio
import logging
import imagehash
from PIL import Image
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.exceptions import TelegramBadRequest
import database

logging.basicConfig(level=logging.INFO)

load_dotenv()
TOKEN = str(os.getenv("TOKEN"))

bot = Bot(token=TOKEN)
dp = Dispatcher()


# ==========================================
# GESTIONE COMANDO /START
# ==========================================
@dp.message(CommandStart())
async def comando_start(message: types.Message):
    if message.chat.type == "private":
        await message.reply("Sono operativo!")

# ==========================================
# GESTIONE FOTO E VIDEO
# ==========================================
@dp.message(F.photo | F.video)
async def gestisci_media(message: types.Message, bot: Bot):
    id_messaggio = message.message_id
    id_gruppo = str(message.chat.id)
    nome_gruppo = message.chat.title or "Chat Privata"

    await database.salva_gruppo(id_gruppo, nome_gruppo)

    doppione_trovato = False
    id_messaggio_originale = None

    # --- CASO FOTO ---
    if message.photo:
        try:
            foto = message.photo[-1]
            id_univoco_telegram = foto.file_unique_id
            # Controllo tramite ID
            risultato_veloce = await database.controllo_id(id_gruppo, id_univoco_telegram)
            
            if risultato_veloce:
                doppione_trovato = True
                id_messaggio_originale = risultato_veloce
                logging.info("Doppione trovato tramite ID")
                
            else:
                # Controllo tramite Hash
                logging.info("ID nuovo, scarico l'immagine per il controllo Hash...")
                file_in_memoria = io.BytesIO()
                await bot.download(foto, destination=file_in_memoria)
                file_in_memoria.seek(0)
                
                immagine = Image.open(file_in_memoria)
                hash_corrente = str(imagehash.phash(immagine))

                risultato_lento = await database.controllo_hash(id_gruppo, hash_corrente, 'photo')
                
                
                if risultato_lento:
                    doppione_trovato = True
                    id_messaggio_originale = risultato_lento
                    logging.info("Doppione trovato tramite Hash")
                else:
                    # File totalmente nuovo! Salviamo sia l'ID che l'Hash
                    await database.aggiungi_al_database(id_gruppo, 'photo', id_univoco_telegram, hash_corrente, id_messaggio)
                    

        except Exception as e:
            logging.error(f"Errore nell'elaborazione della foto: {e}")

    # --- CASO VIDEO ---
    elif message.video:
        try:
            id_univoco_telegram = message.video.file_unique_id
            
            # Controllo tramite ID
            risultato_veloce = await database.controllo_id(id_gruppo, id_univoco_telegram)
            
            if risultato_veloce:
                doppione_trovato = True
                id_messaggio_originale = risultato_veloce
                logging.info("Video doppione trovato tramite ID")
            
            # Controllo tramite l'Hash della miniatura del video
            elif message.video.thumbnail:
                logging.info("ID video nuovo, analizzo la miniatura...")
                miniatura = message.video.thumbnail
                
                # Scarichiamo SOLO la miniatura
                file_in_memoria = io.BytesIO()
                await bot.download(miniatura, destination=file_in_memoria)
                file_in_memoria.seek(0)
                
                # Calcoliamo l'hash della miniatura proprio come se fosse una foto
                immagine = Image.open(file_in_memoria)
                hash_corrente = str(imagehash.phash(immagine))

                risultato_lento = await database.controllo_hash(id_gruppo, hash_corrente, 'video')
                
                if risultato_lento:
                    doppione_trovato = True
                    id_messaggio_originale = risultato_lento
                    logging.info("Video doppione trovato tramite l'Hash della Miniatura!")
                else:
                    await database.aggiungi_al_database(id_gruppo, 'video', id_univoco_telegram, hash_corrente, id_messaggio)
            else:
                # Se il video è nuovo ma NON ha una miniatura, lo salviamo usando solo l'ID
                logging.info("Video senza miniatura, salvo solo l'ID nel database.")
                await database.aggiungi_al_database(id_gruppo, 'video', id_univoco_telegram, "", id_messaggio)
        except Exception as e:
            logging.error(f"Errore nell'elaborazione del video: {e}")


    # ==========================================
    # RISPOSTA FINALE
    # ==========================================
    if doppione_trovato and id_messaggio_originale is not None:
        try:
            await message.answer(
                "⚠️ *Attenzione!* Questo file è un doppione.\nEcco il post originale 👇",
                reply_parameters=types.ReplyParameters(
                    message_id=id_messaggio_originale,
                    allow_sending_without_reply=False
                ),
                parse_mode="Markdown",
                disable_notification=True
            )
        
        # CATTURIAMO L'ERRORE DI TELEGRAM
        except TelegramBadRequest as e:
            if "message to reply not found" in str(e).lower() or "message not found" in str(e).lower() or "reply message not found" in str(e).lower():
                logging.info(f"Il post originale {id_messaggio_originale} è stato eliminato. Promuovo il nuovo post come originale.")
                
                # Ora Pylance è tranquillo, sa già che id_messaggio_originale è un numero!
                await database.aggiorna_messaggio_originale(id_gruppo, id_messaggio_originale, id_messaggio)
            else:
                logging.error(f"Errore di Telegram durante la risposta: {e}")
                
        except Exception as e:
            logging.error(f"Impossibile inviare il messaggio di avviso: {e}")

# ==========================================
# FUNZIONE PRINCIPALE PER AVVIARE IL BOT
# ==========================================
async def main():
    print("Il bot è in fase di avvio...")
    await database.inizializza_database()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())