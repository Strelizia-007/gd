import zipfile, os

with zipfile.ZipFile("gdflix_bot.zip", "w", zipfile.ZIP_DEFLATED) as zf:
    for fname in ["bot.py", "requirements.txt", "README.md"]:
        zf.write(f"gdflix_bot/{fname}", fname)

print("✅ zip created:", os.path.getsize("gdflix_bot.zip"), "bytes")
