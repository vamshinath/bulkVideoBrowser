import os
import shutil
import json
import sys
import gc

import humanize
from flask import Flask, request, jsonify, render_template, send_file
from PIL import Image
from tqdm import tqdm
from pymongo import MongoClient
from collections import Counter

Image.MAX_IMAGE_PIXELS = None

# === Try to import the heavy image processor from fillImageProps_improved ===
FILL_PROPS_DIR = os.path.expanduser("~/gitRepos/filesLookup")
if FILL_PROPS_DIR not in sys.path:
    sys.path.insert(0, FILL_PROPS_DIR)

try:
    from fillImageProps_improved import Config as FillConfig, EnhancedImageProcessor
    FILL_PROPS_AVAILABLE = True
    print("[bulkImage] fillImageProps_improved loaded — full property extraction available")
except ImportError as e:
    FILL_PROPS_AVAILABLE = False
    print(f"[bulkImage] fillImageProps_improved not available ({e}) — quick mode only")

# === Config ===
IMAGES_PER_PAGE = 50
JSONL_FILE = "lastLoad.jsonl"
SEEN_FILE = "seen.txt"
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
PORT = int(os.environ.get("PORT", 5002))

# === Database ===
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["filesLookupUltimate"]

app = Flask(__name__)

# === Session state (consider replacing with per-user sessions for production) ===
_state = {
    "root_dir": "",
    "loaded_images_cache": None,
    "page": 0,
    "sNames": ["_"],
}

SIZE_UNITS = {"B": 1, "KB": 10**3, "MB": 10**6, "GB": 10**9, "TB": 10**12}

# === Lazy-loaded image processor (heavy — only created when needed) ===
_image_processor = None


def _get_image_processor():
    """Lazy-load the EnhancedImageProcessor from fillImageProps_improved."""
    global _image_processor
    if _image_processor is None and FILL_PROPS_AVAILABLE:
        config = FillConfig.from_env()
        # Disable heavy features for browsing context
        config.COMPREHENSIVE_CLIP_ENABLED = False
        config.NSFW_ENABLED = True
        _image_processor = EnhancedImageProcessor(config)
        print("[bulkImage] EnhancedImageProcessor initialised")
    return _image_processor


def _quick_extract_props(filepath):
    """
    Ultra-fast property extraction — dimensions + file size only.
    Used when quickLoad is ON to avoid any heavy processing.
    """
    w = h = pixels = 0
    try:
        with Image.open(filepath) as img:
            w, h = img.size
            pixels = w * h
    except Exception:
        pass

    size = os.path.getsize(filepath)
    return {
        "file": filepath, "w": w, "h": h, "pixels": pixels,
        "face_area": 0, "skinPer": 0,
        "size": size, "hsize": humanize.naturalsize(size),
        "mtime": 0, "nsfw_score": 0, "scoreAvg": -1,
        "suggestedName": "-", "exposedScore": 0, "topExposedLabel": "NaN",
    }


def _full_extract_props(filepath, filehash):
    """
    Full property extraction using EnhancedImageProcessor from fillImageProps_improved.
    Extracts dimensions, skin%, face area, NSFW score, NudeNet labels, sharpness, etc.
    Results are persisted back to MongoDB so future loads are instant.
    """
    processor = _get_image_processor()
    if processor is None:
        return _quick_extract_props(filepath)

    file_size = os.path.getsize(filepath)
    try:
        props = processor.process_image_properties(filepath, file_size)
    except Exception as e:
        print(f"[bulkImage] full extract failed for {filepath}: {e}")
        return _quick_extract_props(filepath)

    if not props:
        return _quick_extract_props(filepath)

    # --- Persist to MongoDB for future fast loads ---
    try:
        db["filesLookupUltimate"].update_one(
            {"filehash": filehash},
            {"$set": {"props": props, "isReady": True}},
            upsert=True,
        )
    except Exception as e:
        print(f"[bulkImage] DB persist failed for {filehash}: {e}")

    # --- Build the browse record from extracted props ---
    sp = props.get("specialProps", {})
    # specialProps may be a list (legacy format from fillImageProps_improved)
    if isinstance(sp, list) and sp:
        sp = sp[0]

    w = props.get("width", 0)
    h = props.get("height", 0)
    size = file_size

    rec = {
        "file": filepath,
        "w": w,
        "h": h,
        "pixels": w * h,
        "face_area": round(props.get("faceArea", 0), 2),
        "skinPer": props.get("skinPer", 0),
        "size": size,
        "hsize": humanize.naturalsize(size),
        "mtime": 0,
        "nsfw_score": props.get("nsfw_score", sp.get("nsfw_score", -1)),
        "scoreAvg": round(sp.get("score_avg", sp.get("scoreAvg", -1)), 2),
        "suggestedName": "-",
        "exposedScore": 0,
        "topExposedLabel": "NaN",
    }

    # Exposed labels scoring (from NudeNet results inside specialProps)
    top_label, top_score = "NaN", float("-inf")
    vals = []
    for label in EXPOSED_LABELS:
        score = sp.get(label)
        if score is not None:
            rec[label] = score
            vals.append(score)
            if score > top_score:
                top_label, top_score = label, score

    rec["exposedScore"] = max(vals) if vals else 0
    if top_score > float("-inf"):
        rec["topExposedLabel"] = f"{top_label.split('_score')[0]}_{round(top_score, 2)}"

    return rec

EXPOSED_LABELS = [
    "ARMPITS_EXPOSED_score", "EXPOSED_ARMPITS_score",
    "BELLY_EXPOSED_score", "EXPOSED_BELLY_score",
    "EXPOSED_BUTTOCKS_score", "BUTTOCKS_EXPOSED_score",
    "EXPOSED_BREAST_F_score", "FEMALE_BREAST_EXPOSED",
    "FEMALE_GENITALIA_EXPOSED", "EXPOSED_GENITALIA_F",
    "ARMPITS_COVERED_area", "ARMPITS_COVERED_score",
    "ARMPITS_EXPOSED_area",
    "BELLY_COVERED_area", "BELLY_COVERED_score",
    "BELLY_EXPOSED_area",
    "BUTTOCKS_COVERED_area", "BUTTOCKS_COVERED_score",
    "BUTTOCKS_EXPOSED_area",
    "COVERED_BELLY_area", "COVERED_BELLY_score",
    "COVERED_BREAST_F_area", "COVERED_BREAST_F_score",
    "COVERED_BUTTOCKS_area", "COVERED_BUTTOCKS_score",
    "COVERED_GENITALIA_F_area", "COVERED_GENITALIA_F_score",
    "EXPOSED_ARMPITS_area",
    "EXPOSED_BELLY_area",
    "EXPOSED_BREAST_F_area",
    "EXPOSED_BUTTOCKS_area",
    "EXPOSED_GENITALIA_F_area", "EXPOSED_GENITALIA_F_score",
    "FEMALE_BREAST_COVERED_area", "FEMALE_BREAST_COVERED_score",
    "FEMALE_BREAST_EXPOSED_area",
    "FEMALE_GENITALIA_COVERED_area", "FEMALE_GENITALIA_COVERED_score",
    "FEMALE_GENITALIA_EXPOSED_area", "FEMALE_GENITALIA_EXPOSED_score",
]

SORT_FIELDS = [
    ("size", "File Size"),
    ("file", "File Name"),
    ("pixels", "Resolution (WxH)"),
    ("skinPer", "skinPer"),
    ("nsfw_score", "nsfw_score"),
    ("face_area", "Face area"),
    ("mtime", "Ctime"),
    ("scoreAvg", "scoreAvg"),
    ("exposedScore", "exposedScore"),
] + [(label, label) for label in [
    "ARMPITS_COVERED_area", "ARMPITS_COVERED_score",
    "ARMPITS_EXPOSED_area", "ARMPITS_EXPOSED_score",
    "BELLY_COVERED_area", "BELLY_COVERED_score",
    "BELLY_EXPOSED_area", "BELLY_EXPOSED_score",
    "BUTTOCKS_COVERED_area", "BUTTOCKS_COVERED_score",
    "BUTTOCKS_EXPOSED_area", "BUTTOCKS_EXPOSED_score",
    "COVERED_BELLY_area", "COVERED_BELLY_score",
    "COVERED_BREAST_F_area", "COVERED_BREAST_F_score",
    "COVERED_BUTTOCKS_area", "COVERED_BUTTOCKS_score",
    "COVERED_GENITALIA_F_area", "COVERED_GENITALIA_F_score",
    "EXPOSED_ARMPITS_area", "EXPOSED_ARMPITS_score",
    "EXPOSED_BELLY_area", "EXPOSED_BELLY_score",
    "EXPOSED_BREAST_F_area", "EXPOSED_BREAST_F_score",
    "EXPOSED_BUTTOCKS_area", "EXPOSED_BUTTOCKS_score",
    "EXPOSED_GENITALIA_F_area", "EXPOSED_GENITALIA_F_score",
    "FEMALE_BREAST_COVERED_area", "FEMALE_BREAST_COVERED_score",
    "FEMALE_BREAST_EXPOSED_area", "FEMALE_BREAST_EXPOSED_score",
    "FEMALE_GENITALIA_COVERED_area", "FEMALE_GENITALIA_COVERED_score",
    "FEMALE_GENITALIA_EXPOSED_area", "FEMALE_GENITALIA_EXPOSED_score",
]]


def parse_size(size_str):
    """Parse a human-readable size string like '10 MB' to bytes."""
    number, unit = size_str.split()
    return int(float(number.strip()) * SIZE_UNITS[unit.strip()])

def load_seen(root_dir):
    """Load seen.txt as set."""
    seen_path = os.path.join(root_dir, SEEN_FILE)
    if os.path.isfile(seen_path):
        with open(seen_path) as f:
            return {ln.strip() for ln in f}
    return set()




def write_jsonl(filepath, records):
    """Append records to JSONL file."""
    with open(filepath, "a", encoding="utf-8") as f:
        for rec in records:
            try:
                f.write(json.dumps(rec) + "\n")
            except Exception as e:
                print('failed:')
                print(rec)

def stream_jsonl(filepath):
    """Stream JSONL line by line (generator)."""
    if not os.path.isfile(filepath):
        return
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue

def get_images_from_directory(root_dir, sort_by, sort_order, load_last, filter_by, quick_load=False):
    """Load image records from JSONL cache or MongoDB, sort and deduplicate.

    Args:
        quick_load: When True, images missing DB props get ultra-fast extraction
                    (dimensions + size only).  When False, full extraction is
                    attempted via EnhancedImageProcessor (NSFW, skin%, face area…).
    """
    already_seen = load_seen(root_dir)
    records, added = [], set()

    if load_last:
        print("Loading from JSONL cache...")
        for rec in tqdm(stream_jsonl(os.path.join(root_dir, JSONL_FILE)), desc="Loading JSONL"):
            if not rec:
                continue
            filepath = rec["file"]
            if filepath in already_seen or filepath in added:
                continue
            if not os.path.isfile(filepath):
                continue
            if filter_by != "_" and rec.get("suggestedName", "_") != filter_by:
                continue

            records.append(rec)
            _state["sNames"].append(rec.get("givenName", rec.get("suggestedName", "-")))
            added.add(filepath)
        print(f"Loaded {len(records)} records from JSONL")
    else:
        records = _load_from_db(root_dir, quick_load=quick_load)

    # Sort and deduplicate
    sorted_records = sorted(records, key=lambda x: x.get(sort_by, -1), reverse=sort_order)
    seen_files = set()
    result = []
    for rec in sorted_records:
        if rec["file"] not in seen_files:
            seen_files.add(rec["file"])
            result.append([
                rec["file"],
                f"{rec['w']}x{rec['h']}",
                rec.get("face_area", 0),
                rec.get("hsize", "0 B"),
                rec.get("skinPer", 0),
                rec.get("nsfw_score", -1),
                rec.get("topExposedLabel", "NaN"),
                rec.get("scoreAvg", -1),
            ])
    return result


def _build_record_from_props(filepath, filehash, props):
    """Extract a record dict from a MongoDB props document."""
    p = props.get("props", {})
    sp = p.get("specialProps", {})

    w = p.get("width", 0)
    h = p.get("height", 0)

    rec = {
        "file": filepath,
        "w": w,
        "h": h,
        "pixels": w * h,
        "face_area": round(p.get("faceArea", 0), 2),
        "skinPer": p.get("skinPer", 0),
        "mtime": props.get("filemtime", 0),
        "nsfw_score": sp.get("nsfw_score", -1),
        "scoreAvg": round(sp.get("scoreAvg", -1), 2),
        "exposedScore": 0,
        "topExposedLabel": "NaN",
    }

    # File size
    raw_size = props.get("filesize", 0)
    if isinstance(raw_size, str):
        rec["size"] = parse_size(raw_size.upper())
    else:
        rec["size"] = raw_size
    rec["hsize"] = humanize.naturalsize(rec["size"])

    # Suggested name
    sname = props.get("givenName", props.get("suggestedName", "-"))
    rec["suggestedName"] = sname
    _state["sNames"].append(sname)

    # Exposed labels scoring
    top_label, top_score = "NaN", float("-inf")
    vals = []
    for label in EXPOSED_LABELS:
        score = sp.get(label)
        if score is not None:
            rec[label] = score
            vals.append(score)
            if score > top_score:
                top_label, top_score = label, score

    rec["exposedScore"] = max(vals) if vals else 0
    if top_score > float("-inf"):
        rec["topExposedLabel"] = f"{top_label.split('_score')[0]}_{round(top_score, 2)}"

    return rec


def _build_fallback_record(filepath, filehash, quick_load=False):
    """Build a record when no DB props exist.

    quick_load=True  → ultra-fast (PIL dimensions + file size only)
    quick_load=False → full extraction via EnhancedImageProcessor, persists to DB
    """
    if quick_load:
        return _quick_extract_props(filepath)
    else:
        return _full_extract_props(filepath, filehash)


def _load_from_db(root_dir, quick_load=False):
    """Load image records from MongoDB.

    quick_load=True  → skip heavy processing for images without cached props
    quick_load=False → run full property extraction for uncached images
    """
    query = {
        "filetype": "image",
        "removed": False,
        "filefullpath": {"$regex": root_dir},
    }
    cursor = db["files"].find(
        query, {"_id": 1, "filehash": 1, "filefullpath": 1}
    ).sort("filesize", 1)
    docs = list(cursor)
    print(f"Total files from DB: {len(docs)}")

    records = []
    batch = []
    jsonl_path = os.path.join(root_dir, JSONL_FILE)
    extracted_count = 0

    for doc in tqdm(docs, unit="img"):
        filehash = doc["filehash"]
        filepath = doc["filefullpath"]
        if not os.path.isfile(filepath):
            continue

        props = db["filesLookup"].find_one({"_id": filehash})
        if props and props.get("props"):
            try:
                rec = _build_record_from_props(filepath, filehash, props)
            except Exception as e:
                print(f"Error processing {filehash}: {e}")
                continue
        else:
            rec = _build_fallback_record(filepath, filehash, quick_load=quick_load)
            extracted_count += 1
            # Periodic memory cleanup during full extraction
            if not quick_load and extracted_count % 10 == 0:
                gc.collect()

        batch.append(rec)
        if len(batch) >= 100:
            write_jsonl(jsonl_path, batch)
            records.extend(batch)
            batch.clear()

    if batch:
        write_jsonl(jsonl_path, batch)
        records.extend(batch)

    return records

@app.route('/')
def index():
    """Render the main page with sort fields and name counts."""
    counter = Counter(_state["sNames"])
    result = sorted(
        [[name, count] for name, count in counter.items()],
        key=lambda x: x[1],
        reverse=True,
    )
    return render_template('Imageindex.html', sort_fields=SORT_FIELDS, sNames=result)


def _validate_path_under_root(filepath):
    """Ensure the given path is under the current root_dir to prevent path traversal."""
    root = _state["root_dir"]
    if not root:
        return False
    real_path = os.path.realpath(filepath)
    real_root = os.path.realpath(root)
    return real_path.startswith(real_root + os.sep) or real_path == real_root


@app.route('/load_images', methods=['POST'])
def load_images():
    """Load a page of images from the given directory."""
    directory = request.form.get('directory_path')
    sort_by = request.form.get('sort_by', 'size')
    sort_order = request.form.get('sort_order', 'asc') != 'asc'
    load_last = request.form.get("loadLast") == "true"
    quick_load = request.form.get("quickLoad") == "true"
    filter_by = request.form.get('filter_by', '-')

    if not directory or not os.path.isdir(directory):
        return jsonify({'images': [], 'error': 'Invalid directory path'}), 400

    _state["root_dir"] = directory
    _state["page"] += 1
    page = _state["page"]

    if _state["loaded_images_cache"] is None:
        mode = "quick" if quick_load else "full"
        print(f"First load — building image cache (mode={mode})...")
        _state["loaded_images_cache"] = get_images_from_directory(
            directory, sort_by, sort_order, load_last, filter_by,
            quick_load=quick_load,
        )

    start = (page - 1) * IMAGES_PER_PAGE
    end = start + IMAGES_PER_PAGE
    images_on_page = _state["loaded_images_cache"][start:end]

    return jsonify({
        'images': images_on_page,
        'total_images': len(_state["loaded_images_cache"]),
    })


@app.route('/serve_image')
def serve_image():
    """Serve an image file from disk."""
    image_path = request.args.get('image_path')
    if not image_path or not os.path.isfile(image_path):
        return jsonify({'error': 'Image not found'}), 404
    if not _validate_path_under_root(image_path):
        return jsonify({'error': 'Access denied'}), 403
    return send_file(image_path)


@app.route('/keep_image', methods=['POST'])
def keep_image():
    """Mark image as seen and move it to a _kept directory."""
    image_path = request.form.get('image_name')
    root = _state["root_dir"]
    if not image_path or not os.path.isfile(image_path):
        return jsonify({'success': False, 'error': 'Image not found'}), 400
    if not _validate_path_under_root(image_path):
        return jsonify({'success': False, 'error': 'Access denied'}), 403

    seen_path = os.path.join(root, SEEN_FILE)
    with open(seen_path, 'a') as f:
        f.write(image_path + "\n")

    target_dir = root + "_kept"
    os.makedirs(target_dir, exist_ok=True)

    try:
        shutil.move(image_path, os.path.join(target_dir, os.path.basename(image_path)))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/delete_image', methods=['POST'])
def delete_image():
    """Delete an image file from disk."""
    image_path = request.form.get('image_name')
    if not image_path or not os.path.isfile(image_path):
        return jsonify({'success': False, 'error': 'Image not found'}), 400
    if not _validate_path_under_root(image_path):
        return jsonify({'success': False, 'error': 'Access denied'}), 403

    try:
        os.remove(image_path)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/move_image', methods=['POST'])
def move_image():
    """Move an image file to a _moved directory."""
    image_path = request.form.get('image_name')
    root = _state["root_dir"]
    if not image_path or not os.path.isfile(image_path):
        return jsonify({'success': False, 'error': 'Image not found'}), 400
    if not _validate_path_under_root(image_path):
        return jsonify({'success': False, 'error': 'Access denied'}), 403

    target_dir = root + "_moved"
    os.makedirs(target_dir, exist_ok=True)

    try:
        shutil.move(image_path, os.path.join(target_dir, os.path.basename(image_path)))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/extract_props', methods=['POST'])
def extract_props():
    """On-demand full property extraction for a single image.

    Runs EnhancedImageProcessor and returns the extracted properties.
    Useful when browsing in quick-load mode and wanting details for one image.
    """
    image_path = request.form.get('image_path')
    if not image_path or not os.path.isfile(image_path):
        return jsonify({'success': False, 'error': 'Image not found'}), 400
    if not _validate_path_under_root(image_path):
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    if not FILL_PROPS_AVAILABLE:
        return jsonify({'success': False, 'error': 'fillImageProps_improved not available'}), 503

    # Look up the filehash from MongoDB
    doc = db["files"].find_one(
        {"filefullpath": image_path},
        {"filehash": 1},
    )
    filehash = doc["filehash"] if doc else "unknown"

    try:
        rec = _full_extract_props(image_path, filehash)
        return jsonify({
            'success': True,
            'props': {
                'w': rec.get('w', 0),
                'h': rec.get('h', 0),
                'face_area': rec.get('face_area', 0),
                'skinPer': rec.get('skinPer', 0),
                'nsfw_score': rec.get('nsfw_score', 0),
                'scoreAvg': rec.get('scoreAvg', -1),
                'exposedScore': rec.get('exposedScore', 0),
                'topExposedLabel': rec.get('topExposedLabel', 'NaN'),
                'hsize': rec.get('hsize', '0 B'),
            },
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/reset_cache', methods=['POST'])
def reset_cache():
    """Reset the loaded images cache so the next load rebuilds it."""
    _state["loaded_images_cache"] = None
    _state["page"] = 0
    return jsonify({'success': True, 'message': 'Cache cleared'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT)
