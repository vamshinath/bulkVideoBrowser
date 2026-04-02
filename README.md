# Bulk Media Browser

A pair of Flask-based web tools for **rapidly triaging large collections of videos and images**. Built for power users who need to review thousands of media files, keep the good ones, delete the junk, and skip the rest — all from a fast, keyboard-driven dark-mode UI.

---

## Table of Contents

- [Overview](#overview)
- [Scripts](#scripts)
  - [1. Video Browser (`app.py`)](#1-video-browser-apppy)
  - [2. Image Browser (`bulkImage.py`)](#2-image-browser-bulkimagepy)
  - [3. Auto-Loader (`simulatePosts.py`)](#3-auto-loader-simulatepostspy)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Setup — From Scratch on a New Machine](#setup--from-scratch-on-a-new-machine)
  - [Step 1: System Dependencies](#step-1-system-dependencies)
  - [Step 2: MongoDB](#step-2-mongodb)
  - [Step 3: Clone the Repo](#step-3-clone-the-repo)
  - [Step 4: Python Environment](#step-4-python-environment)
  - [Step 5: Install Python Packages](#step-5-install-python-packages)
  - [Step 6: Optional — fillImageProps_improved](#step-6-optional--fillimageprops_improved)
  - [Step 7: Populate MongoDB](#step-7-populate-mongodb)
- [Usage](#usage)
  - [Running the Video Browser](#running-the-video-browser)
  - [Running the Image Browser](#running-the-image-browser)
  - [Running the Auto-Loader](#running-the-auto-loader)
- [Keyboard Shortcuts](#keyboard-shortcuts)
- [File & Folder Reference](#file--folder-reference)
- [How Each Script Works (Deep Dive)](#how-each-script-works-deep-dive)
- [Configuration & Environment Variables](#configuration--environment-variables)
- [Troubleshooting](#troubleshooting)

---

## Overview

When you have tens of thousands of media files — scraped, downloaded, or collected over time — you need a fast way to decide what to **keep**, **delete**, or **skip**. Opening each file in a media player is impossibly slow.

These tools serve media files through a local web UI that lets you:

- View 2+ videos (or 50+ images) at a time in a grid
- **OK / Keep** → mark as reviewed (write to `okList.txt` / `seen.txt`, optionally move)
- **Delete** → permanently remove the file from disk
- **Skip** → move to a `skipped/` subfolder for later review
- Track stats: how many reviewed, deleted, disk space saved
- Use keyboard shortcuts to fly through hundreds of files per minute

---

## Scripts

### 1. Video Browser (`app.py`)

**Purpose:** Rapidly browse and triage video files in a directory.

**Port:** `9898`

**How it works:**

1. You enter a directory path and choose sort/filter options on the landing page.
2. The app queries **MongoDB** (`filesLookupUltimate` database) for all video files under that directory. MongoDB stores pre-computed metadata: file hash, file path, size, resolution, duration, etc.
3. Videos are sorted by your chosen field (size, resolution, duration, bitrate, quality score, creation time, etc.) and served 2 at a time.
4. For each video card you can:
   - **OK** → appends the file path to `<directory>/okList.txt` and loads the next video
   - **Delete** → permanently deletes the file from disk and loads the next
   - **Skip** → moves the file to `<directory>/skipped/` and loads the next
5. A session queue holds the remaining videos in memory so no re-scanning is needed.
6. Videos auto-play at 1.5× speed, starting at 15% into the timeline, so you get to the action fast.
7. A **"Load Last"** option reloads from `<directory>/lastLoad.json` (the previous session's file list) instead of re-querying MongoDB — useful for resuming.

**Key features:**
- Dark-mode UI optimized for video viewing
- Sticky stats bar (reviewed / OK / deleted / skipped / disk saved)
- Global playback speed control (0.5× – 4×)
- Keyboard shortcuts: `1` OK, `2` Delete, `3` Skip
- Delete confirmation modal to prevent accidents
- Toast notifications instead of alert popups
- Smooth card transition animations
- Fullscreen button per video
- Video overlay badges (resolution, duration, file size)
- Filename display with link
- Bitrate and creation date metadata

**Generated files per directory:**
| File | Purpose |
|---|---|
| `okList.txt` | One filepath per line — videos marked OK (excluded from future loads) |
| `lastLoad.json` | Full video list from last load — enables "Load Last" resume |
| `skipped/` | Subfolder where skipped videos are moved to |

---

### 2. Image Browser (`bulkImage.py`)

**Purpose:** Rapidly browse, sort, and triage image files with rich metadata (NSFW scores, face area, skin percentage, NudeNet labels, etc.).

**Port:** `5002` (configurable via `PORT` env var)

**How it works:**

1. You enter a directory path, pick sort/filter options, and click **Load**.
2. The app queries **MongoDB** for all image files under that directory.
3. For each image, it looks up pre-computed properties from the `filesLookup` collection (width, height, skin%, face area, NSFW score, NudeNet exposed-label scores, etc.).
4. Images missing cached properties can be processed in two modes:
   - **Quick Load** (checkbox ON) → ultra-fast: only extracts dimensions + file size via PIL
   - **Full Load** (checkbox OFF) → runs `EnhancedImageProcessor` from `fillImageProps_improved` for NSFW scoring, face detection, skin analysis, NudeNet labels — then persists results back to MongoDB
5. Images are displayed 50 per page in a configurable grid (1–6 columns).
6. For each image you can:
   - **Keep** → marks as seen (`seen.txt`), moves file to `<directory>_kept/`
   - **Delete** → permanently removes from disk
   - **Move** → moves file to `<directory>_moved/`
   - **Analyze** → on-demand full property extraction for a single image (useful in quick-load mode)
7. A **lightbox** opens on click for full-screen review with action buttons and arrow navigation.
8. **Bulk actions**: select multiple images (click select buttons or `A` to select all), then bulk keep/delete/move.
9. **Filter by name** — if images have `suggestedName` / `givenName` metadata, you can filter the list.

**Key features:**
- Dark-mode grid UI with adjustable column count (slider)
- Sticky control panel and stats bar
- Pagination (50 images per page, ← → arrow keys)
- Lightbox with full image preview + action buttons + arrow nav
- NSFW score color-coded badges (red > 0.7, yellow > 0.4, blue > 0.1)
- Metadata overlays: dimensions, size, face area, skin%, NudeNet labels, average score
- Bulk select + bulk keep/delete/move
- On-demand property analysis per image
- Cache reset button (clears in-memory cache, re-queries DB)
- Keyboard shortcuts (see below)
- JSONL cache file for fast reload (`lastLoad.jsonl`)
- Toast notifications

**Generated files per directory:**
| File | Purpose |
|---|---|
| `seen.txt` | One filepath per line — images already reviewed |
| `lastLoad.jsonl` | JSONL cache of all loaded image records — enables "Load Last" |
| `<directory>_kept/` | Sibling folder where kept images are moved |
| `<directory>_moved/` | Sibling folder where moved images are placed |

---

### 3. Auto-Loader (`simulatePosts.py`)

**Purpose:** A background watchdog that automatically triggers image loading when `bulkImage.py` is idle.

**How it works:**

1. Runs in an infinite loop (every 5 minutes).
2. Checks the memory usage of the `bulkImage.py` process using `psutil`.
3. If RSS memory is below ~1 GB (meaning it's idle / not actively loading), it sends a POST request to `/load_images` with pre-configured parameters to start loading the next batch.
4. If memory is high, it assumes the server is already busy and skips.

**Use case:** Leave this running alongside `bulkImage.py` so it pre-loads the next batch of images while you review the current batch.

---

## Architecture

```
┌──────────────┐       ┌──────────────────┐       ┌──────────────┐
│   Browser    │◄─────►│  Flask Server    │◄─────►│   MongoDB    │
│  (Dark UI)   │ HTTP  │  app.py (video)  │ Query │filesLookup-  │
│              │       │  bulkImage.py    │       │  Ultimate    │
│              │       │   (image)        │       │              │
└──────────────┘       └───────┬──────────┘       └──────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   Local Filesystem  │
                    │  (video/image files │
                    │   okList, seen.txt, │
                    │   lastLoad, etc.)   │
                    └─────────────────────┘
```

**Database:** Both scripts read from the same MongoDB database (`filesLookupUltimate`):
- **`files` collection** — master file index: `filefullpath`, `filehash`, `filesize`, `filetype` ("video"/"image"), `isReady`, `removed`
- **`filesLookup` collection** — property cache keyed by file hash: dimensions, duration, NSFW scores, face area, skin%, NudeNet labels, etc.

> **Note:** These collections must be pre-populated by an external indexing pipeline (e.g., `filesLookup` repo) before this tool can work.

---

## Prerequisites

| Dependency | Required By | Purpose |
|---|---|---|
| **Python 3.9+** | All | Runtime |
| **MongoDB 4.4+** | All | File index + property cache |
| **pip** | All | Python package manager |
| **FFmpeg** | `app.py` | Video codec support (used by OpenCV) |
| **libgl1** | `app.py` | OpenCV display backend on headless Linux |
| **`fillImageProps_improved`** | `bulkImage.py` (optional) | Full NSFW/face/skin analysis. Located at `~/gitRepos/filesLookup/`. Without it, only quick-load mode works. |

---

## Setup — From Scratch on a New Machine

### Step 1: System Dependencies

```bash
# Ubuntu / Debian
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git ffmpeg libgl1-mesa-glx

# Fedora / RHEL
sudo dnf install -y python3 python3-pip git ffmpeg mesa-libGL
```

### Step 2: MongoDB

```bash
# Ubuntu 22.04+ (MongoDB 7.0)
# Import the MongoDB public GPG key
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | \
  sudo gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor

# Add the repository
echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | \
  sudo tee /etc/apt/sources.list.d/mongodb-org-7.0.list

sudo apt update
sudo apt install -y mongodb-org

# Start and enable
sudo systemctl start mongod
sudo systemctl enable mongod

# Verify
mongosh --eval "db.runCommand({ ping: 1 })"
```

> MongoDB must be running on `localhost:27017` (default). The database `filesLookupUltimate` with collections `files` and `filesLookup` must be pre-populated by your file indexing pipeline.

### Step 3: Clone the Repo

```bash
mkdir -p ~/gitRepos && cd ~/gitRepos
git clone https://github.com/vamshinath/bulkVideoBrowser.git
cd bulkVideoBrowser
```

### Step 4: Python Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### Step 5: Install Python Packages

```bash
pip install flask pymongo humanize opencv-python pillow filehash tqdm psutil requests
```

**Full package list:**

| Package | Version (approx.) | Used By | Purpose |
|---|---|---|---|
| `flask` | ≥ 2.3 | Both | Web framework |
| `pymongo` | ≥ 4.0 | Both | MongoDB driver |
| `humanize` | ≥ 4.0 | Both | Human-readable file sizes |
| `opencv-python` | ≥ 4.8 | `app.py` | Video metadata (imported but used for CV2 support) |
| `pillow` | ≥ 10.0 | `bulkImage.py` | Image dimension extraction |
| `filehash` | ≥ 0.2 | `app.py` | SHA256 file hashing |
| `tqdm` | ≥ 4.65 | Both | Progress bars in terminal |
| `psutil` | ≥ 5.9 | `simulatePosts.py` | Process memory monitoring |
| `requests` | ≥ 2.31 | `simulatePosts.py` | HTTP requests to trigger loading |

### Step 6: Optional — fillImageProps_improved

For full image analysis (NSFW scoring, face detection, skin analysis, NudeNet labels) in `bulkImage.py`:

```bash
cd ~/gitRepos
git clone <your-filesLookup-repo-url> filesLookup
cd filesLookup
pip install -r requirements.txt  # install its dependencies
```

`bulkImage.py` expects `fillImageProps_improved.py` at `~/gitRepos/filesLookup/fillImageProps_improved.py`. It imports:
- `Config` — configuration class (loaded from env vars)
- `EnhancedImageProcessor` — the heavy image analysis engine

If this module is not available, `bulkImage.py` will still work but only in **quick-load mode** (dimensions + file size only — no NSFW/face/skin analysis).

### Step 7: Populate MongoDB

Both tools expect a pre-populated MongoDB database. The collections must follow this schema:

**`files` collection** (master index):
```json
{
  "_id": "ObjectId",
  "filehash": "sha256-hex-string",
  "filefullpath": "/absolute/path/to/file.mp4",
  "filesize": 12345678,
  "filetype": "video",       // or "image"
  "isReady": true,
  "removed": false
}
```

**`filesLookup` collection** (property cache, keyed by `_id` = filehash):
```json
{
  "_id": "sha256-hex-string",
  "filefullpath": "/absolute/path/to/file.mp4",
  "filesize": 12345678,
  "filectime": 1700000000,
  "filemtime": 1700000000,
  "props": {
    "width": 1920,
    "height": 1080,
    "duration": 120.5,          // video only (seconds)
    "faceArea": 0.15,           // image only
    "skinPer": 32.5,            // image only
    "nsfw_score": 0.02,         // image only
    "specialProps": {           // image only — NudeNet labels, scores
      "nsfw_score": 0.02,
      "scoreAvg": 0.45,
      "FEMALE_BREAST_EXPOSED_score": 0.01,
      ...
    }
  }
}
```

> This data is typically created by a separate indexing/crawling tool (the `filesLookup` pipeline). These browser tools are the **consumption/triage** layer.

---

## Usage

### Running the Video Browser

```bash
cd ~/gitRepos/bulkVideoBrowser
source venv/bin/activate
python app.py
```

Open **http://localhost:9898** in your browser.

1. Enter the directory path containing your video files
2. Choose sort field, sort order, and whether to resume last session
3. Click **Load Videos**
4. Triage: use buttons or keyboard shortcuts (`1` OK, `2` Delete, `3` Skip)

### Running the Image Browser

```bash
cd ~/gitRepos/bulkVideoBrowser
source venv/bin/activate
python bulkImage.py
```

Open **http://localhost:5002** in your browser.

1. Enter the directory path containing your image files
2. Choose sort field (NSFW score, size, resolution, skin%, face area, etc.)
3. Choose sort order and options:
   - **Load Last** — reload from JSONL cache (fast resume)
   - **Quick** — skip heavy analysis for uncached images
4. Click **Load**
5. Browse the grid, click images for lightbox, use overlay buttons or keyboard shortcuts
6. Use the grid slider to adjust column count (1–6)
7. Select multiple images and use bulk actions (Keep/Delete/Move)

### Running the Auto-Loader

```bash
cd ~/gitRepos/bulkVideoBrowser
source venv/bin/activate
python simulatePosts.py
```

> Edit the `data` dict inside `simulatePosts.py` to set your target directory and sort options. Runs in background, polling every 5 minutes.

---

## Keyboard Shortcuts

### Video Browser (`app.py`)

| Key | Action |
|---|---|
| `1` | OK (mark first video as reviewed) |
| `2` | Delete (opens confirmation for first video) |
| `3` | Skip (move first video to skipped/) |
| `Esc` | Close delete confirmation modal |
| `Enter` | Confirm delete (when modal is open) |

### Image Browser (`bulkImage.py`)

| Key | Action |
|---|---|
| `←` / `→` | Previous / Next page (grid) or image (lightbox) |
| `D` | Delete current image (lightbox) |
| `K` | Keep current image (lightbox) |
| `M` | Move current image (lightbox) |
| `A` | Select all images on page (grid) |
| `X` | Deselect all (grid) |
| `Esc` | Close lightbox |

---

## File & Folder Reference

```
bulkVideoBrowser/
├── app.py                      # Video browser Flask server (port 9898)
├── bulkImage.py                # Image browser Flask server (port 5002)
├── simulatePosts.py            # Auto-loader watchdog for bulkImage.py
├── README.md                   # This file
├── templates/
│   ├── index.html              # Video browser — landing/config page
│   ├── videos.html             # Video browser — main triage UI
│   ├── Imageindex.html         # Image browser — single-page app (grid + lightbox)
│   └── Imageindex.html.bak     # Backup of previous Imageindex.html version
```

**Runtime files created per directory:**

| File/Folder | Created By | Purpose |
|---|---|---|
| `okList.txt` | Video browser | Paths of videos marked OK |
| `lastLoad.json` | Video browser | Cached video list for "Load Last" |
| `skipped/` | Video browser | Videos that were skipped |
| `seen.txt` | Image browser | Paths of images already reviewed |
| `lastLoad.jsonl` | Image browser | JSONL cache of image records |
| `<dir>_kept/` | Image browser | Sibling directory for kept images |
| `<dir>_moved/` | Image browser | Sibling directory for moved images |

---

## How Each Script Works (Deep Dive)

### Video Browser Flow (`app.py`)

```
User enters directory + options
        │
        ▼
   POST / → redirect to /videos?directory=...&sort_by=...
        │
        ▼
  get_videos(directory, sort_by)
        │
        ├── load_last=True? → Read lastLoad.json, filter out okList.txt entries
        │
        └── load_last=False? → Query MongoDB files collection
                │                (filetype=video, isReady=True, regex on path)
                ▼
            For each file → lookup filesLookup collection for props
                │            (width, height, duration, etc.)
                ▼
            Sort by chosen field → Save to lastLoad.json
        │
        ▼
  Render videos.html with first 2 videos
  Store remaining videos in server-side session dict
        │
        ▼
  User clicks OK/Delete/Skip (or presses 1/2/3)
        │
        ▼
  POST /ok, /delete, or /skip
        │
        ├── Updates okList.txt / deletes file / moves to skipped/
        ├── Pops next video from session queue
        └── Returns next video JSON + updated stats
        │
        ▼
  Frontend animates out old card, animates in new card
  Updates stats bar + shows toast notification
```

### Image Browser Flow (`bulkImage.py`)

```
User enters directory + options → clicks Load
        │
        ▼
  POST /load_images
        │
        ├── First call → build cache:
        │     ├── load_last=True? → Stream lastLoad.jsonl
        │     └── load_last=False? → Query MongoDB
        │           ├── Props found in DB? → Build record from cached props
        │           └── No props?
        │                 ├── quickLoad=True? → PIL dimensions + file size only
        │                 └── quickLoad=False? → EnhancedImageProcessor (NSFW, face, skin...)
        │                                        → Persist results back to MongoDB
        │     Sort + deduplicate → Store in memory cache
        │
        ├── Paginate: return 50 images for requested page
        │
        ▼
  Frontend renders grid with metadata badges
        │
        ▼
  User clicks image → Lightbox opens
  User clicks Keep/Delete/Move/Analyze (or keyboard shortcut)
        │
        ▼
  POST /keep_image, /delete_image, /move_image, or /extract_props
        │
        ├── keep: append to seen.txt + move to <dir>_kept/
        ├── delete: os.remove()
        ├── move: move to <dir>_moved/
        └── extract_props: run full EnhancedImageProcessor, return results
        │
        ▼
  Frontend removes card from grid + shows toast
```

---

## Configuration & Environment Variables

| Variable | Default | Used By | Purpose |
|---|---|---|---|
| `MONGO_URI` | `mongodb://localhost:27017/` | `bulkImage.py` | MongoDB connection string |
| `PORT` | `5002` | `bulkImage.py` | HTTP port for image browser |

`app.py` is hardcoded to port `9898` and `mongodb://localhost:27017/`. Edit the file to change.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| **"Invalid directory path"** | Ensure the path exists and is accessible by the Python process |
| **No videos/images load** | Verify MongoDB has data: `mongosh --eval "use filesLookupUltimate; db.files.countDocuments({filetype:'video'})"` |
| **Videos don't play in browser** | Ensure files are MP4 with H.264 codec. MKV/AVI may not play natively — transcode with FFmpeg |
| **`fillImageProps_improved not available`** | Expected unless you've set up `~/gitRepos/filesLookup/`. Quick-load mode still works. |
| **High memory usage in `bulkImage.py`** | Full extraction is memory-intensive. Use Quick Load for browsing, Analyze individual images on demand |
| **Port already in use** | Change the port: `PORT=5003 python bulkImage.py` or edit `app.py` |
| **OpenCV import error** | Install: `sudo apt install libgl1-mesa-glx` and `pip install opencv-python` |
| **Permission denied on delete/move** | Ensure the Python process has write permissions to the target directories |
