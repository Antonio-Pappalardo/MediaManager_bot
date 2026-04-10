import aiosqlite
import imagehash

DB_NAME = "bot_database.db"

# ==========================================
# 1. DATABASE INITIALIZATION
# ==========================================
async def initialize_database():
    """Creates the database and tables if they do not exist."""
    async with aiosqlite.connect(DB_NAME) as db:
        
        # Table for saved media files
        await db.execute('''
            CREATE TABLE IF NOT EXISTS saved_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT,
                media_type TEXT,
                unique_id TEXT,
                media_hash TEXT,
                message_id INTEGER
            )
        ''')

        # Table for authorized groups
        await db.execute('''
            CREATE TABLE IF NOT EXISTS authorized_groups (
                group_id TEXT PRIMARY KEY,
                group_name TEXT
            )
        ''')
        await db.commit()
        print("Database initialized successfully.")


# ==========================================
# 2. FAST CHECK (ID ONLY)
# ==========================================
async def check_id(group_id: str, unique_id: str):
    """Checks if the exact Telegram unique ID already exists in the database."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT message_id FROM saved_files WHERE group_id = ? AND unique_id = ?", 
            (group_id, unique_id)
        ) as cursor:
            result = await cursor.fetchone()
            if result:
                return result[0]
            return None


# ==========================================
# 3. SLOW CHECK (PERCEPTUAL HASH)
# ==========================================
async def check_hash(group_id: str, current_hash_str: str, media_type: str): 
    """Compares the perceptual hash of the incoming media with stored hashes."""
    current_hash = imagehash.hex_to_hash(current_hash_str)
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT media_hash, message_id FROM saved_files WHERE group_id = ? AND media_type = ?", 
            (group_id, media_type)
        ) as cursor:
            async for row in cursor:
                db_hash_str = row[0]
                message_id = row[1]
                
                if not db_hash_str:
                    continue
                    
                db_hash = imagehash.hex_to_hash(db_hash_str)
                # Compare hashes (Hamming distance). Threshold is 5.
                if current_hash - db_hash <= 5:
                    return message_id 
    return None


# ==========================================
# 4. SAVE AND UPDATE RECORDS
# ==========================================
async def add_to_database(group_id: str, media_type: str, unique_id: str, media_hash: str, message_id: int):
    """Saves a new media record into the database."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            INSERT INTO saved_files (group_id, media_type, unique_id, media_hash, message_id)
            VALUES (?, ?, ?, ?, ?)
        ''', (group_id, media_type, unique_id, media_hash, message_id))
        await db.commit()

async def update_original_message(group_id: str, old_message_id: int, new_message_id: int):
    """Updates the message ID of a file if the original post was deleted."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            UPDATE saved_files 
            SET message_id = ? 
            WHERE group_id = ? AND message_id = ?
        ''', (new_message_id, group_id, old_message_id))
        await db.commit()


# ==========================================
# 5. PERMISSIONS & GROUP MANAGEMENT
# ==========================================
async def authorize_group(group_id: str, group_name: str = "Unknown"):
    """Adds or updates a group in the authorized list."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            INSERT OR REPLACE INTO authorized_groups (group_id, group_name) 
            VALUES (?, ?)
        ''', (group_id, group_name))
        await db.commit()

async def revoke_group(group_id: str):
    """Removes a group from the authorized list and deletes its saved files."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM authorized_groups WHERE group_id = ?", (group_id,))
        await db.execute("DELETE FROM saved_files WHERE group_id = ?", (group_id,))
        await db.commit()

async def check_permission_and_name(group_id: str):
    """Checks if a group is authorized and returns its stored name."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT group_name FROM authorized_groups WHERE group_id = ?', (group_id,)) as cursor:
            result = await cursor.fetchone()
            return result[0] if result else None

async def get_authorized_groups():
    """Retrieves a list of all authorized groups and their names."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT group_id, group_name FROM authorized_groups') as cursor:
            return await cursor.fetchall()