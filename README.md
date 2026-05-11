# GDFlix Share Telegram Bot

A Python Telegram bot that shares Google Drive links to GDFlix via its share API.
Admin-only access. Supports single file links, folder links, and auto-series packs.

---

## Requirements

```
pip install python-telegram-bot requests beautifulsoup4
```

---

## Configuration (edit bot.py)

| Variable       | Description                                      |
|----------------|--------------------------------------------------|
| `BOT_TOKEN`    | Your bot token from @BotFather                   |
| `ADMIN_IDS`    | List of allowed Telegram user IDs (integers)     |
| `GDFLIX_API`   | Your GDFlix API key                              |
| `GAPI_KEY`     | Google Drive API key (for folder listing)        |

### Getting your Telegram user ID
Message @userinfobot on Telegram.

### Getting a Google Drive API key
1. Go to https://console.cloud.google.com
2. Enable the **Google Drive API**
3. Create an API key under Credentials
4. Paste it as `GAPI_KEY` in bot.py

> Without a Google API key, the bot cannot list folder contents.
> The bot uses `GOOGLE_API_KEY` env var if set.

---

## Usage

```bash
python bot.py
```

### Commands

| Command | Description |
|---------|-------------|
| `/start` | Show help |
| `/series <folder_link>` | Process a global series folder (auto-detects S01, S02...) |
| `/upload <link> | <pack_name>` | Manually upload with a custom pack name |

### Sending links directly
Just paste any Google Drive link as a message:
- **File link** → uploads to GDFlix using filename as pack name
- **Folder with subfolders** → triggers series mode automatically
- **Folder without subfolders** → uploaded as single pack

---

## How Pack Names Are Built

Given the first filename in a season folder:
```
Duck.&.Goose.2023.S01E01.Find.Something.Round.Fuzzy.Field.1080p.ATVP.WEB-DL.Atmos.SDR.H.264-LioN.mkv
```
The bot strips the extension, removes the episode token (E01), and keeps:
```
Duck.&.Goose.2023.S01.1080p.ATVP.WEB-DL.Atmos.SDR.H.264-LioN
```

For S02, it reads the first file in the S02 subfolder and applies the same logic.

---

## GDFlix API

The bot POSTs to `https://new18.gdflix.net/share` with:
```json
{
  "api":   "<your_api_key>",
  "title": "<pack_name>",
  "url":   "<gdrive_link>"
}
```
Response is scraped for pack name, pack link, and individual file links.

---

## Notes

- GDrive links must be **publicly accessible** (Anyone with the link can view)
- Bot uses a 1-second delay between each season upload to avoid rate limiting
- The site response scraper handles both JSON and HTML responses
- If scraping returns empty results, the raw response (first 200 chars) is shown
