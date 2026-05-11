
import os
import re
import asyncio
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# ─── CONFIG ──────────────────────────────────────────────────────────────────
BOT_TOKEN  = "YOUR_BOT_TOKEN_HERE"          # from @BotFather
ADMIN_IDS  = [123456789]                    # your Telegram user ID(s)
GDFLIX_URL = "https://new18.gdflix.net/share"
GDFLIX_API = "4c6758a8a132729b75e0ba3fc2d7b28a"

# Google Drive API key — needed to list folder contents
# Enable Drive API at https://console.cloud.google.com and create a key
GAPI_KEY   = os.getenv("GOOGLE_API_KEY", "")
GAPI_BASE  = "https://www.googleapis.com/drive/v3"

# ─── ADMIN GUARD ─────────────────────────────────────────────────────────────
def is_admin(update: Update) -> bool:
    return update.effective_user.id in ADMIN_IDS

def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update):
            await update.message.reply_text("⛔ Not authorised.")
            return
        await func(update, context)
    return wrapper

# ─── GOOGLE DRIVE HELPERS ────────────────────────────────────────────────────
def extract_gdrive_id(link: str) -> tuple:
    """Returns (type, id). type = 'file' | 'folder' | 'unknown'"""
    folder_pat = r"drive\.google\.com/drive/(?:u/\d+/)?folders/([a-zA-Z0-9_-]+)"
    file_pat   = r"drive\.google\.com/(?:file/d/|open\?id=)([a-zA-Z0-9_-]+)"
    if m := re.search(folder_pat, link):
        return ("folder", m.group(1))
    if m := re.search(file_pat, link):
        return ("file", m.group(1))
    return ("unknown", link.strip())

def gdrive_list_folder(folder_id: str) -> list:
    params = {
        "q":        f"'{folder_id}' in parents and trashed=false",
        "fields":   "files(id,name,mimeType)",
        "orderBy":  "name",
        "pageSize": 1000,
    }
    if GAPI_KEY:
        params["key"] = GAPI_KEY
    r = requests.get(f"{GAPI_BASE}/files", params=params, timeout=20)
    r.raise_for_status()
    return r.json().get("files", [])

def gdrive_file_link(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"

def gdrive_folder_link(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}"

# ─── PACK NAME BUILDER ───────────────────────────────────────────────────────
def build_pack_name(first_filename: str) -> str:
    """
    Input:  Duck.&.Goose.2023.S01E01.Find.Something.Round.1080p.ATVP.WEB-DL.Atmos.SDR.H.264-LioN.mkv
    Output: Duck.&.Goose.2023.S01.1080p.ATVP.WEB-DL.Atmos.SDR.H.264-LioN

    Logic:
      1. Strip file extension
      2. Find S##E## pattern
      3. Keep everything before S## + the season tag (S##)
      4. Drop the episode-specific title words between E## and quality token
      5. Append from first quality token (1080p, 720p, 2160p, 4K…) onward
    """
    name = re.sub(r'\.[a-zA-Z0-9]{2,4}$', '', first_filename)   # strip extension

    season_ep = re.search(r'(S\d{2})(E\d{2,3})', name, re.IGNORECASE)
    if not season_ep:
        return name   # unparseable, return as-is

    season_tag  = season_ep.group(1).upper()        # e.g. S01
    before_sep  = name[:season_ep.start()].rstrip('.')
    after_ep    = name[season_ep.end():]             # everything after E01

    quality_pat = re.search(r'(2160p|1080p|720p|480p|4K)', after_ep, re.IGNORECASE)
    if quality_pat:
        suffix = after_ep[quality_pat.start():].lstrip('.')
    else:
        suffix = after_ep.lstrip('.')

    return f"{before_sep}.{season_tag}.{suffix}"

# ─── GDFLIX API ──────────────────────────────────────────────────────────────
def gdflix_upload(pack_name: str, gdrive_link: str) -> requests.Response:
    payload = {"api": GDFLIX_API, "title": pack_name, "url": gdrive_link}
    return requests.post(GDFLIX_URL, json=payload,
                         headers={"Content-Type": "application/json"}, timeout=30)

def parse_gdflix_response(resp: requests.Response) -> dict:
    """Try JSON first, fall back to HTML scraping."""
    result = {"pack_name": "", "pack_link": "", "file_links": []}
    try:
        data = resp.json()
        result["pack_name"]  = data.get("title") or data.get("name", "")
        result["pack_link"]  = data.get("link")  or data.get("url", "")
        result["file_links"] = data.get("files") or data.get("links") or []
        return result
    except Exception:
        pass

    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        if "gdflix" in href or "drive.google" in href:
            if not result["pack_link"]:
                result["pack_link"] = href
                result["pack_name"] = text
            else:
                result["file_links"].append({"name": text, "link": href})
    return result

# ─── UPLOAD & REPORT ─────────────────────────────────────────────────────────
async def upload_and_report(update: Update, gdrive_link: str, pack_name: str, status_msg=None):
    if status_msg:
        await status_msg.edit_text(f"⬆️ Uploading...\n📦 `{pack_name}`", parse_mode="Markdown")
    else:
        status_msg = await update.message.reply_text(
            f"⬆️ Uploading...\n📦 `{pack_name}`", parse_mode="Markdown")

    resp = gdflix_upload(pack_name, gdrive_link)

    if resp.status_code not in (200, 201):
        await status_msg.edit_text(
            f"❌ Upload failed (HTTP {resp.status_code})\n```{resp.text[:300]}```",
            parse_mode="Markdown")
        return

    s = parse_gdflix_response(resp)
    text  = f"✅ *Upload Successful!*\n\n"
    text += f"📦 *Pack:* `{s['pack_name'] or pack_name}`\n"
    if s["pack_link"]:
        text += f"🔗 *Pack Link:* {s['pack_link']}\n"
    if s["file_links"]:
        text += "\n📄 *Files:*\n"
        for f in s["file_links"][:20]:
            n = f.get("name", "File")
            l = f.get("link", "")
            text += f"• [{n}]({l})\n"
    if not s["pack_link"] and not s["file_links"]:
        text += f"\n_Raw response:_ `{resp.text[:200]}`"

    await status_msg.edit_text(text, parse_mode="Markdown", disable_web_page_preview=True)

# ─── COMMANDS ────────────────────────────────────────────────────────────────
@admin_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *GDFlix Share Bot*\n\n"
        "Just paste a Google Drive link — I'll handle the rest.\n\n"
        "*Commands:*\n"
        "• `/start` — show this help\n"
        "• `/series <folder_link>` — process series (auto season subfolders)\n"
        "• `/upload <link> | <pack name>` — manual upload with custom name\n\n"
        "*Auto-detection (plain message):*\n"
        "• File link → uploaded with filename as pack name\n"
        "• Folder with subfolders → auto series mode\n"
        "• Folder without subfolders → single pack upload",
        parse_mode="Markdown"
    )

@admin_only
async def cmd_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/upload <gdrive_link> | <pack_name>"""
    args = " ".join(context.args)
    if "|" not in args:
        await update.message.reply_text(
            "Usage: `/upload <gdrive_link> | <pack_name>`", parse_mode="Markdown")
        return
    link, pname = [x.strip() for x in args.split("|", 1)]
    await upload_and_report(update, link, pname)

@admin_only
async def cmd_series(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/series <global_gdrive_folder_link>"""
    if not context.args:
        await update.message.reply_text(
            "Usage: `/series <gdrive_folder_link>`", parse_mode="Markdown")
        return

    folder_link = context.args[0]
    _, folder_id = extract_gdrive_id(folder_link)
    status = await update.message.reply_text("🔍 Scanning folder for season subfolders...")

    try:
        items = gdrive_list_folder(folder_id)
    except Exception as e:
        await status.edit_text(f"❌ Could not list folder: {e}\n💡 Make sure GAPI_KEY is set.")
        return

    FOLDER_MIME = "application/vnd.google-apps.folder"
    subfolders  = sorted(
        [i for i in items if i["mimeType"] == FOLDER_MIME],
        key=lambda x: x["name"].lower()
    )

    if not subfolders:
        await status.edit_text("⚠️ No subfolders found. Try `/upload` for a single folder.")
        return

    await status.edit_text(f"📂 Found {len(subfolders)} season(s). Starting uploads...")
    results = []

    for sf in subfolders:
        sf_name = sf["name"]
        sf_link = gdrive_folder_link(sf["id"])

        try:
            sf_files = sorted(
                [f for f in gdrive_list_folder(sf["id"]) if f["mimeType"] != FOLDER_MIME],
                key=lambda x: x["name"].lower()
            )
        except Exception as e:
            results.append(f"❌ *{sf_name}*: Could not list — {e}")
            continue

        if not sf_files:
            results.append(f"⚠️ *{sf_name}*: Empty, skipped.")
            continue

        pack_name = build_pack_name(sf_files[0]["name"])
        await status.edit_text(
            f"⬆️ Uploading *{sf_name}*...\n📦 `{pack_name}`", parse_mode="Markdown")

        resp = gdflix_upload(pack_name, sf_link)
        if resp.status_code not in (200, 201):
            results.append(f"❌ *{sf_name}*: HTTP {resp.status_code}")
            continue

        s    = parse_gdflix_response(resp)
        line = f"✅ *{sf_name}*\n📦 `{s['pack_name'] or pack_name}`"
        if s["pack_link"]:
            line += f"\n🔗 {s['pack_link']}"
        if s["file_links"]:
            for fl in s["file_links"][:5]:
                line += f"\n  • [{fl.get('name','')}]({fl.get('link','')})"
        results.append(line)

        await asyncio.sleep(1)  # rate-limit politeness

    summary = "\n\n".join(results)
    await status.edit_text(
        f"🎬 *Series Upload Complete!*\n\n{summary}",
        parse_mode="Markdown", disable_web_page_preview=True)

@admin_only
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auto-detect GDrive link from plain message."""
    text = update.message.text or ""
    gtype, gid = extract_gdrive_id(text)

    if gtype == "unknown":
        await update.message.reply_text(
            "ℹ️ Send a Google Drive link, or use /upload for custom pack names.")
        return

    if gtype == "folder":
        waiting = await update.message.reply_text("🔍 Inspecting folder...")
        try:
            items = gdrive_list_folder(gid)
        except Exception as e:
            await waiting.edit_text(
                f"❌ Cannot list folder: {e}\n💡 Set your Google API key.")
            return

        FOLDER_MIME = "application/vnd.google-apps.folder"
        subfolders  = [i for i in items if i["mimeType"] == FOLDER_MIME]

        if subfolders:
            # Series mode
            context.args = [text]
            await waiting.delete()
            await cmd_series(update, context)
        else:
            # Single folder upload
            files = sorted(
                [i for i in items if i["mimeType"] != FOLDER_MIME],
                key=lambda x: x["name"].lower()
            )
            pack = build_pack_name(files[0]["name"]) if files else gid
            await upload_and_report(update, gdrive_folder_link(gid), pack, waiting)

    else:
        # Single file — use ID as fallback pack name (user can't get filename without API)
        pack = gid
        await upload_and_report(update, gdrive_file_link(gid), pack)

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("upload",  cmd_upload))
    app.add_handler(CommandHandler("series",  cmd_series))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
