# DJ Library

A local browser app and command-line organizer for macOS and Rekordbox. Uses **genre → energy → BPM** folders and musical key in filenames. Reads existing tags, detects exact duplicates, previews changes, verifies copies, and exports an M3U playlist for import into Rekordbox. Your original files and Rekordbox database are left in place.

## Offline Mac installer

If the chat attachment cannot be downloaded, install from this repository instead:

```sh
git clone --branch dj-library-mac --single-branch https://github.com/titodv41/music.git "$HOME/DJ-Library-Installer"
bash "$HOME/DJ-Library-Installer/Install.command"
```

The source installer downloads the pinned official slskd and mutagen artifacts over HTTPS, verifies their SHA-256 hashes, builds the offline package locally, and runs it. It does not require Python certificate setup because downloads use macOS's curl with verification enabled. If the clone folder already exists, keep it and use a different new folder name for another clone.

The downloadable Intel Mac package includes the app, mutagen, and an official slskd 0.24.5 build compatible with Monterey's .NET 8 support. Extract `DJ-Library-Mac.zip` in Downloads and run:

```sh
bash "$HOME/Downloads/DJ-Library/Install.command"
```

It verifies its bundled artifacts, creates a private Python environment, installs the dependencies offline, makes a Desktop launcher, and opens your browser. It needs your existing Python 3.10+; it does not need Codex, Docker, Homebrew, or administrator access. Keep the Terminal window open. Press Control-C to stop the app and its managed slskd process. See [START-HERE.txt](START-HERE.txt).

App files go under `~/Applications/DJ Library`. Reports and journals go under `~/Library/Application Support/DJ Library`. The browser app binds to loopback only and uses a per-session token, origin checks, and host checks. Its slskd web API also binds to loopback and uses generated authentication. Soulseek peer traffic is a separate network protocol and listener. No directories are automatically shared.

The Soulseek tab starts the bundled client after you supply credentials locally. Passwords are not saved by the organizer. Close other Soulseek clients using the same account first. Completed transfers land in `~/Music/DJ Inbox`. Search results prefer filenames containing `extended`; this does not prove they are the correct version. Select a result to queue its exact remote file, inspect transfers, then analyze completed files in Mixed In Key and scan the inbox.

Mixed In Key analysis/tag writing and Rekordbox playlist import remain manual. The Open Mixed In Key button launches the installed app; it does not automate its GUI. macOS may require folder permissions and approval of downloaded executables in Security & Privacy. The installer preserves Gatekeeper and quarantine protections.

## Install on your Mac

Install Python 3.10+ if needed, then run Terminal in this repository:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
dj-library --help
```

No subscription or cloud upload is needed to organize files. Audio and reports stay local. Reports contain file paths and music metadata; keep them private as appropriate.

## Analyze and organize

1. In Mixed In Key, analyze your music and enable writing key, BPM, and energy results to supported file tags. Exact options depend on your version. This app does not launch or automate Mixed In Key. Verify a few files with `scan` before processing the whole library. Supported containers include MP3, FLAC, AIFF, WAV, M4A, Ogg and Opus; tag availability varies by container.
2. Scan the **actual audio folder**, which may differ from your Rekordbox database folder. Substitute your paths below. Choose an output report that does not already exist.

```sh
dj-library scan "$HOME/Music/Downloads" --output scan.json
dj-library summary scan.json
dj-library plan scan.json "$HOME/Music/DJ Organized"
```

The summary suggests a layout after inspecting your tags. Missing genres, energy, BPM, or key are reported explicitly. Energy must be a tagged 1–10 value; it is never inferred from loudness or artist. Readable Mixed In Key comment fields include `Energy 7` and Camelot keys such as `8A`. If results are missing, check Mixed In Key's tag-writing settings, then rescan. Genre comes from existing tags, not an audio classifier. Exact duplicates are skipped; alternate encodes and alternate mixes need manual review.

3. Review the plan, then copy into a folder separate from the source:

```sh
dj-library copy scan.json "$HOME/Music/DJ Organized" --journal copies.jsonl
dj-library playlist scan.json "$HOME/Music/DJ Organized" --output organized.m3u8
```

Example folder: `Tech House/Energy 07/125-129 BPM/Artist - Title [8A]--<hash>.flac`. Full content hashes prevent filename collisions. Repeating a copy skips identical files. Source changes since scanning stop the operation; scan again after retagging. Allow space for a second copy of your collection.

Import the `.m3u8` playlist into Rekordbox and verify a small batch before using it at a gig. Importing copies can create additional collection entries; this tool does not migrate cues, grids, playlists, history, or existing track references. M3U import has not been validated against your Rekordbox version.

To undo files created by a copy run:

```sh
dj-library undo copies.jsonl
```

Undo deletes only journaled copies whose hashes still match, never originals. It stops if a copy was modified. Empty directories remain. Keep the journal; abrupt process termination or disk failure can leave a copy that was not journaled. Undo does not remove Rekordbox collection entries.

## Discover extended mixes

```sh
dj-library discover
dj-library discover 'ANOTR Relax My Eyes'
```

Produces Spotify, SoundCloud and Beatport search links using your artist references: Ben Sterling, Mau P, Solomun, Joseph Capriati, Prospa, ANOTR, Brunello, Beltran, David Guetta and Vintage Culture. These are discovery links, not verified matches. Check artist, remix, duration and audio quality before adding a version. Spotify audio downloading is not supported. Use artist-enabled SoundCloud downloads or purchased files, then analyze and scan them.

Automatic Spotify/SoundCloud favorites syncing, audio classification, and automatic extended-version matching are not implemented. The browser app includes discovery links and a persistent local wishlist. Previous ChatGPT conversations are unavailable to this app; paste any additional preferences yourself.

## Soulseek via local slskd (optional)

The browser app and Mac installer manage slskd for you. For the alternative command-line adapter below, install and configure [slskd](https://github.com/slskd/slskd) separately with your Soulseek account, download directory and a local API key. Keep the service bound to localhost. Supply `SLSKD_API_KEY` securely in your Terminal environment; do not put it in this repository. `SLSKD_URL` defaults to `http://127.0.0.1:5030` and only loopback hosts are accepted.

```sh
dj-library soulseek-search 'ANOTR extended mix'
dj-library soulseek-results SEARCH_ID
dj-library soulseek-download USERNAME 'EXACT_REMOTE_FILENAME' FILE_SIZE_IN_BYTES
```

Searches are asynchronous: use the returned search ID and fetch results later. Select a specific result, verify its metadata, and pass its exact filename and size to download. Only download files you have permission to obtain. slskd handles transfer status and saves audio to its configured directory; analyze those files in Mixed In Key before scanning. No automatic bulk downloads or shared-folder changes are performed. Live Soulseek search and transfer are **unverified** without your Mac, slskd service, and credentials.

## Development

```sh
python -m unittest discover -s tests -v
```

Tests generate real tagged audio fixtures and exercise scanning, organization, duplicate handling, copy verification, playlist export and undo. No music files are bundled.

Set `DJ_TEST_SLSKD` to a verified native slskd executable to include the actual authenticated API startup test (no Soulseek connection is made). The optional `scripts/smoke_ui.py` exercises scan, preview, copy, playlist creation, undo, wishlist and discovery in Chromium using Playwright. These are developer tools, not Mac runtime dependencies.

Build the offline package with `python scripts/build_mac.py --assets PATH_TO_VERIFIED_ARCHIVES`. Required filenames and pinned upstream hashes are in that script. The package includes upstream licenses and source archives. The Mac launch, actual Soulseek login/transfers, Mixed In Key output and Rekordbox import must still be validated on the user's Mac; Linux validation does not establish them.
