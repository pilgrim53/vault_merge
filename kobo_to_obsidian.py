#!/usr/bin/env python3
import os
import sqlite3
from datetime import datetime

# --- CONFIG ---
# Where your Kobo is mounted when plugged in
KOBO_MOUNT_PATH = "/home/tinker/kobo" 
DB_PATH = os.path.join(KOBO_MOUNT_PATH, ".kobo", "KoboReader.sqlite")

# Where your Obsidian vault lives
OBSIDIAN_VAULT_PATH = "/mnt/saphira/PKM"  #
HIGHLIGHTS_SUBFOLDER = "/mnt/saphira/PKM/Self/Books 2026/Highlights"        

OUTPUT_DIR = os.path.join(OBSIDIAN_VAULT_PATH, HIGHLIGHTS_SUBFOLDER)

# OPTIONAL:   Only export highlights newer than this many days (7 for weekly)
LOOKBACK_DAYS = 7
# --- END CONFIG ---

# insert a pause here to instruct the user to mount the Kobo device

input("Press Enter after mounting the Kobo device...")
print(f'Run the following:  "sudo mount /dev/sdb {KOBO_MOUNT_PATH}" ')



def connect_db(db_path: str):
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Cannot find Kobo database at: {db_path}")
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def get_recent_highlights(conn):
    """
    Returns list of rows:
    (book_id, book_title, author, highlight_text, annotation, highlight_datetime)
    """
    cur = conn.cursor()

    # Kobo stores annotations/highlights in Bookmark table; Text is highlight text.[web:8]
    # DateCreated or DateModified can be used for recency filters depending on firmware.[web:8]
    query = """
    SELECT
        c.ContentID      AS book_id,
        c.Title          AS title,
        c.Attribution    AS author,
        b.Text           AS highlight_text,
        b.Annotation     AS note_text,
        b.DateCreated    AS created_at
    FROM Bookmark b
    JOIN content c ON b.VolumeID = c.ContentID
    WHERE b.Text IS NOT NULL
      AND b.Text <> ''
    ORDER BY c.Title, b.StartContainerPath;
    """

    cur.execute(query)
    rows = cur.fetchall()
    return rows


def ensure_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def sanitize_filename(name: str) -> str:
    # Simple filesystem-safe slug
    bad_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    for ch in bad_chars:
        name = name.replace(ch, "-")
    return name.strip().replace("  ", " ")


def write_to_obsidian(highlights):
    """
    Group highlights by book, write/append a markdown file per book.
    """
    ensure_output_dir()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Group by book_id
    books = {}
    for book_id, title, author, h_text, note_text, created_at in highlights:
        books.setdefault(book_id, {
            "title": title or "Untitled",
            "author": author or "Unknown",
            "items": []
        })
        books[book_id]["items"].append({
            "highlight": h_text.strip(),
            "note": (note_text or "").strip(),
            "created_at": created_at
        })

    for book_id, data in books.items():
        title = data["title"]
        author = data["author"]  # use only the first 2 names of the author if multiple
        author = " ".join(author.split(" ")[:2]) if author else "Unknown"
    
        filename = sanitize_filename(f"{title} - {author}.md")
        path = os.path.join(OUTPUT_DIR, filename)

        # If file does not exist, create with header
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# {title}\n")
                f.write(f"**Author**: {author}\n\n")
                f.write(f"_Kobo highlights imported on {now_str}_\n\n")

        # Append highlights
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n## Import {now_str}\n\n")
            for item in data["items"]:
                h = item["highlight"]
                note = item["note"]
                f.write(f"> {h}\n\n")
                if note:
                    f.write(f"- **Note**: {note}\n\n")


def main():
    conn = None
    try:
        conn = connect_db(DB_PATH)
        highlights = get_recent_highlights(conn)

        # Optional: do recency filtering in Python if you want true "weekly"
        # using created_at and LOOKBACK_DAYS, depending on how your firmware
        # formats DateCreated (often ISO string or Unix timestamp).[web:8]

        if not highlights:
            print("No highlights found.")
            return

        write_to_obsidian(highlights)
        print("Highlights exported to Obsidian.")
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()



