# vault_merge

`vault_merge` is a Git merge helper for resolving merge conflicts inside an Obsidian vault. It lets Git operate on the underlying Markdown files in a controlled way so you get clean, line‑based merges even when multiple devices or users edit the same notes.

## Overview

This repo contains:

- A merge helper script (`vault-merge.sh`) for Obsidian vault content.
- Git configuration (via `.gitattributes`) to associate Obsidian notes with the custom merge driver.
- Supporting pieces for local development and optional CI usage.[web:88]

## Features

- Designed for Git‑tracked Obsidian vaults stored as plain Markdown.[web:88]
- Runs a three‑way merge on note files to keep changes from different branches or machines.
- Can be wired to apply opinionated conflict handling rules for frontmatter, links, and metadata.
- Fails safely if the merge cannot be resolved automatically, leaving standard conflict markers for manual fixes.

## Requirements

- Git
- Bash / POSIX‑compatible shell
- An Obsidian vault stored in a Git repository (Markdown files on disk)

## Installation

Clone the repository into (or alongside) your Obsidian vault repo:

```bash
git clone git@github.com:pilgrim53/vault_merge.git
cd vault_merge
```

Make the helper executable:

```bash
chmod +x vault-merge.sh
```

Configure the merge driver in your Obsidian vault repo (adjust the path to `vault-merge.sh` as needed):

```bash
git config --local merge.obsidian-vault.driver "./vault-merge.sh %O %A %B %L %P"
git config --local merge.obsidian-vault.name "Obsidian vault merge driver"
```
[web:86][web:88]

In your vault repo, configure `.gitattributes` so Git knows which files should use this driver, for example:

```gitattributes
*.md merge=obsidian-vault
.obsidian/workspace.json merge=obsidian-vault
```
[web:71][web:88]

Commit the configuration:

```bash
git add vault-merge.sh .gitattributes
git commit -m "Configure Obsidian vault merge helper"
```

## Usage

1. Keep working in Obsidian as usual; ensure your vault is stored in this Git repository.
2. When you merge branches or pull from another device, Git will invoke `vault-merge.sh` for files marked with `merge=obsidian-vault`.[web:86][web:88]
3. The script:
   - Receives the ancestor, current, and incoming versions of the note.
   - Runs a merge on the Markdown content.
   - Writes the merged note back to the working tree file.
4. If automatic resolution is not possible, Git leaves conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) in the Markdown file; open it in Obsidian or a text editor, resolve manually, then commit.[web:88]

## Development

- Use feature branches for changes to the merge behavior (e.g., how YAML frontmatter or link blocks are merged).
- Document any opinionated rules (like preferring newer frontmatter or preserving all link references).
- Open a PR describing the change and an example Obsidian note that demonstrates the behavior.

## Notes on Obsidian

- Obsidian treats the vault as a folder of Markdown files; Git and this helper operate directly on those files.[web:88]
- Be careful when syncing across multiple devices; always pull and merge before heavy editing to minimize conflicts.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.