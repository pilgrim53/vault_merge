# PKM sync — two-channel architecture
Added 2026-11-22 at Martin's direction. This amends the flow design in the
PKM Sync Setup and Operation Guide: content between Martin and Trinity moves
in two strictly one-way channels. Direction is a safety property, not a
convenience setting.

## The two channels

### Channel 1 — Trinity → Martin's phone ("From Trinity")
- Drive location: `gdrive:Muse/From Trinity/`
- Contents: files Trinity creates for Martin — coaching notes, briefs,
  documents, anything authored by Trinity for delivery.
- Flow: Trinity writes into the Drive folder (via the shared "Muse" folder)
  → pkm-sync collects it into the vault → the phone push phase carries it to
  the phone.
- Rule: ONLY Trinity-authored files ever enter this channel. pkm-sync must
  never place Martin's own notes, journal entries, or vault copies into it.

### Channel 2 — Martin → Trinity ("Shared from vault")
- Drive location: `gdrive:Muse/Shared from vault/`
- Contents: COPIES of Martin's notes that he chooses to give Trinity —
  currently `Journal/`, `Projects/`, `Self/` (copied 2026-11-22).
- Flow: vault → Drive. One way. Terminal.
- Rule: **Nothing in this channel ever flows back to the phone, under any
  guise — not as Trinity content, not as a "synced" copy, not ever.** These
  are Martin's originals' copies, given for Trinity to read. The phone
  already has the originals; a returning copy would be a duplicate wearing
  a false provenance, and it would corrupt the one thing the system exists
  to protect: Martin always knows which words are his and which are hers.

## Enforcement points in pkm-sync
1. The phone-push phase builds its file set ONLY from Channel 1
   (`Muse/From Trinity` as collected into the vault). `Shared from vault`
   is not a permissible source path for any phone-bound phase; treat its
   presence in a push set as a fatal configuration error and abort.
2. The collect/publish phase for Channel 2 writes ONLY to
   `gdrive:Muse/Shared from vault`. It never reads from it for distribution.
3. The channels' trees are disjoint by path. No hard links, no shared
   staging directory, no "helpful" merging step.
4. Trinity's own discipline mirrors the sync rules: she writes only into
   `From Trinity` (and her pre-existing outputs area of `Muse`), and treats
   `Shared from vault` as read-only even though the share technically
   permits edits. What Martin gives as a copy stays byte-identical to what
   he gave.

## Why (Martin's words, paraphrased once, then law)
"I choose what goes in and I choose what you see." Provenance is the point:
Martin's notes are his mind; Trinity's files are her work. The channels keep
the border visible in both directions — the same split-brain principle as
the Coaching Charter, applied to flow instead of storage.
