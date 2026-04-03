import aiosqlite
import imagehash

NOME_DB = "bot_database.db"

# ==========================================
# 1. CREAZIONE DELLE TABELLE
# ==========================================
async def inizializza_database():
    """Crea il database e le tabelle se non esistono già."""
    async with aiosqlite.connect(NOME_DB) as db:
        # Tabella per la rubrica dei gruppi
        await db.execute('''
            CREATE TABLE IF NOT EXISTS gruppi (
                id_gruppo TEXT PRIMARY KEY,
                nome_gruppo TEXT
            )
        ''')
        
        # Tabella per i file
        await db.execute('''
            CREATE TABLE IF NOT EXISTS file_salvati (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_gruppo TEXT,
                tipo_media TEXT,
                id_univoco TEXT,
                hash_foto TEXT,
                id_messaggio INTEGER
            )
        ''')
        await db.commit()
        print("Database inizializzato con successo.")


# ==========================================
# 2. CONTROLLO VELOCE (FAST PATH - SOLO ID)
# ==========================================
async def controllo_id(id_gruppo: str, id_univoco: str):
    """Cerca se l'ID esatto di Telegram esiste già per questo gruppo."""
    async with aiosqlite.connect(NOME_DB) as db:
        # Cerchiamo l'id_messaggio corrispondente a questo id_univoco
        async with db.execute(
            "SELECT id_messaggio FROM file_salvati WHERE id_gruppo = ? AND id_univoco = ?", 
            (id_gruppo, id_univoco)
        ) as cursore:
            risultato = await cursore.fetchone()
            
            if risultato:
                return risultato[0]  # Ritorna l'ID del messaggio originale
            return None              # Nessun doppione trovato


# ==========================================
# 3. CONTROLLO LENTO (SLOW PATH - HASH VISIVO)
# ==========================================
async def controllo_hash(id_gruppo: str, hash_corrente_str: str, tipo_media: str): 
    hash_corrente = imagehash.hex_to_hash(hash_corrente_str)
    
    async with aiosqlite.connect(NOME_DB) as db:
        async with db.execute(
            "SELECT hash_foto, id_messaggio FROM file_salvati WHERE id_gruppo = ? AND tipo_media = ?", 
            (id_gruppo, tipo_media)
        ) as cursore:
            
            async for riga in cursore:
                db_hash_str = riga[0]
                id_messaggio = riga[1]
                
                if not db_hash_str:
                    continue
                    
                db_hash = imagehash.hex_to_hash(db_hash_str)
                
                if hash_corrente - db_hash <= 5:
                    return id_messaggio 
                    
    return None


# ==========================================
# 4. SALVATAGGIO NUOVO FILE
# ==========================================
async def aggiungi_al_database(id_gruppo: str, tipo_media: str, id_univoco: str, hash_foto: str, id_messaggio: int):
    """Salva il nuovo file nel database."""
    async with aiosqlite.connect(NOME_DB) as db:
        await db.execute('''
            INSERT INTO file_salvati (id_gruppo, tipo_media, id_univoco, hash_foto, id_messaggio)
            VALUES (?, ?, ?, ?, ?)
        ''', (id_gruppo, tipo_media, id_univoco, hash_foto, id_messaggio))
        await db.commit()

# ==========================================
# 5. SALVATAGGIO GRUPPO (RUBRICA)
# ==========================================
async def salva_gruppo(id_gruppo: str, nome_gruppo: str):
    """Salva o aggiorna il nome del gruppo nella rubrica del bot."""
    async with aiosqlite.connect(NOME_DB) as db:
        await db.execute('''
            INSERT OR REPLACE INTO gruppi (id_gruppo, nome_gruppo)
            VALUES (?, ?)
        ''', (id_gruppo, nome_gruppo))
        await db.commit()

async def aggiorna_messaggio_originale(id_gruppo: str, id_messaggio_vecchio: int, id_messaggio_nuovo: int):
    """Se il post originale è stato cancellato, elegge il nuovo file come originale."""
    async with aiosqlite.connect(NOME_DB) as db:
        await db.execute('''
            UPDATE file_salvati 
            SET id_messaggio = ? 
            WHERE id_gruppo = ? AND id_messaggio = ?
        ''', (id_messaggio_nuovo, id_gruppo, id_messaggio_vecchio))
        await db.commit()