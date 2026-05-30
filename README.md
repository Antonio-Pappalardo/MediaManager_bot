# MediaManager_bot

A Python-based Telegram bot designed to detect and manage duplicate media (photos and videos) across multiple groups. Built with Aiogram 3 and SQLite, it prioritizes performance and efficient resource usage.

## Technical Overview

* **Dual-Layer Detection:** Uses Telegram's `file_unique_id` for instant matches, backed by Perceptual Hashing (pHash) to detect resized, compressed, or slightly modified images.
* **Optimized Video Processing:** Computes hashes exclusively from video thumbnails to bypass heavy file downloads.
* **Access Control Shield:** Implements an early-return mechanism for unauthorized groups, ensuring zero computational and memory overhead for unapproved chats.
* **Asynchronous Design:** Fully non-blocking I/O operations using `aiogram` and `aiosqlite`.
* **Database Consistency:** Automatically updates records to promote new messages as the "original" if the initial source message is deleted by a user.

## Setup Instructions

### 1. Clone the repository
```bash
git clone https://github.com/Antonio-Pappalardo/MediaManager_bot.git
cd MediaManager_bot
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configuration
Create a `.env` file in the project root directory and add your credentials:
```env
TOKEN=your_telegram_bot_token
ADMIN_ID=your_telegram_user_id
```

### 4. Run the bot
```bash
python main.py
```

## Admin Commands

* `/start` - Check bot status
* `/commands` - View available admin actions
* `/list` - Display all authorized groups
* `/authorize [ID]` - Grant bot access to a specific group
* `/revoke [ID]` - Remove access and delete associated group data
