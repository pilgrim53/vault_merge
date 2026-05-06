from pathlib import Path
from datetime import datetime
import os
import sqlite3
import subprocess
import shutil


def ensure_rsync_available():
    """Verify rsync is installed and available on PATH."""
    if shutil.which("rsync") is None:
        raise FileNotFoundError("rsync is not installed or not available in PATH")


def rsync_sync(source_dir: Path, destination_dir: Path):
    """Sync files from source to destination using rsync.

    This preserves timestamps, copies only newer files, and excludes Obsidian
    metadata/trash folders.
    """
    source_dir = Path(source_dir)
    destination_dir = Path(destination_dir)

    if not source_dir.exists():
        raise FileNotFoundError(f"Source directory does not exist: {source_dir}")

    destination_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "rsync",
        "-a",
        "--update",
        "--itemize-changes",
        "--exclude", ".obsidian/",
        "--exclude", ".trash/",
        "--exclude", ".smart-env/",
        f"{source_dir}/",
        str(destination_dir),
    ]

    print(f"\nRunning rsync from {source_dir} to {destination_dir}")
    subprocess.run(cmd, check=True)


def merge_directories(pc_dir: Path, phone_dir: Path):
    """Merge files bidirectionally between PC and phone directories using rsync."""
    ensure_rsync_available()

    print("\nSyncing Phone -> PC")
    rsync_sync(phone_dir, pc_dir)

    print("\nSyncing PC -> Phone")
    rsync_sync(pc_dir, phone_dir)


# ========== KOBO IMPORT FUNCTIONALITY ==========

def connect_db(db_path: str):
    """Connect to Kobo SQLite database."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Cannot find Kobo database at: {db_path}")
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def get_recent_highlights(conn):
    """Return recent highlights from Kobo database."""
    cur = conn.cursor()

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
    return cur.fetchall()


def ensure_output_dir(output_dir):
    """Ensure output directory exists."""
    os.makedirs(output_dir, exist_ok=True)


def sanitize_filename(name: str) -> str:
    """Make filename filesystem-safe."""
    bad_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    for ch in bad_chars:
        name = name.replace(ch, "-")
    return name.strip().replace("  ", " ")


def write_to_obsidian(highlights, output_dir):
    """Group highlights by book and write Markdown files."""
    ensure_output_dir(output_dir)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

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
        author = data["author"]
        author = " ".join(author.split(" ")[:2]) if author else "Unknown"

        filename = sanitize_filename(f"{title} - {author}.md")
        path = os.path.join(output_dir, filename)

        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# {title}\n")
                f.write(f"**Author**: {author}\n\n")
                f.write(f"_Kobo highlights imported on {now_str}_\n\n")

        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n## Import {now_str}\n\n")
            for item in data["items"]:
                h = item["highlight"]
                note = item["note"]
                f.write(f"> {h}\n\n")
                if note:
                    f.write(f"- **Note**: {note}\n\n")


def kobo_import(kobo_mount_path, obsidian_vault_path):
    """Import Kobo highlights into an Obsidian vault."""
    db_path = os.path.join(kobo_mount_path, ".kobo", "KoboReader.sqlite")
    highlights_subfolder = "Self/Books 2026/Highlights"
    output_dir = os.path.join(obsidian_vault_path, highlights_subfolder)

    conn = None
    try:
        print(f"Connecting to Kobo database at: {db_path}")
        conn = connect_db(db_path)
        highlights = get_recent_highlights(conn)

        if not highlights:
            print("No highlights found in Kobo database.")
            return

        print(f"Found {len(highlights)} highlights. Writing to Obsidian...")
        write_to_obsidian(highlights, output_dir)
        print(f"Highlights exported to: {output_dir}")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Make sure the Kobo device is mounted at the expected location.")
    finally:
        if conn:
            conn.close()


def main():
    PHONE_DIR = Path("/mnt/android/Internal storage/Documents/Martin PKM")
    PC_DIR = Path("/home/martin/PKM")
    KOBO_MOUNT_PATH = "/mnt/kobo"

    print("\n" + "=" * 60)
    print("OBSIDIAN VAULT MERGE & KOBO IMPORT UTILITY")
    print("=" * 60)
    print("\nChoose an operation:")
    print("  1) Merge files between Phone and PC using rsync")
    print("  2) Import highlights from Kobo device")
    print("  3) Exit")

    choice = input("\nEnter your choice (1-3) [1]: ").strip() or "1"

    if choice == "1":
        print("\nMerging new/updated files between Phone and PC using rsync...")
        print("Phone Directory:", PHONE_DIR)
        print("PC Directory:", PC_DIR)
        try:
            merge_directories(PC_DIR, PHONE_DIR)
        except FileNotFoundError as exc:
            print(f"Error: {exc}")
        except subprocess.CalledProcessError as exc:
            print(f"rsync failed with exit code {exc.returncode}")
    elif choice == "2":
        if not os.path.exists(KOBO_MOUNT_PATH):
            print(f"\nError: Kobo mount path not found: {KOBO_MOUNT_PATH}")
            print("Please mount your Kobo device first.")
            return

        print(f"\nImporting Kobo highlights...")
        print(f"Kobo Mount Path: {KOBO_MOUNT_PATH}")
        print(f"PC Directory: {PC_DIR}")
        kobo_import(KOBO_MOUNT_PATH, str(PC_DIR))
    elif choice == "3":
        print("\nExiting...")
        return
    else:
        print("\nInvalid choice. Please enter 1, 2, or 3.")


if __name__ == "__main__":
    main()
