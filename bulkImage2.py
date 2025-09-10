import os, shutil, json, humanize, logging
from flask import Flask, request, jsonify, render_template, send_file
from PIL import Image
from tqdm import tqdm
from pymongo import MongoClient
from collections import Counter

Image.MAX_IMAGE_PIXELS = None
logging.basicConfig(level=logging.INFO)

# === Config ===
IMAGES_PER_PAGE = 50
JSONL_FILE = "lastLoad.jsonl"
SEEN_FILE = "seen.txt"
mongoClient = MongoClient("mongodb://localhost:27017/")
db = mongoClient["filesLookup"]

# === Flask app ===
app = Flask(__name__)
root_dir = ""
loaded_images_cache = None
sNames = ["_"]

# === Predefined labels (avoid redefining every call) ===
EXPOSED_LABELS = [
    "ARMPITS_EXPOSED_score", "BELLY_EXPOSED_score", "BUTTOCKS_EXPOSED_score",
    "EXPOSED_BREAST_F_score", "FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED",
    "EXPOSED_GENITALIA_F"
]


# --- Helpers ---
def load_seen(root_dir):
    """Load seen.txt as set."""
    seen_path = os.path.join(root_dir, SEEN_FILE)
    if os.path.isfile(seen_path):
        with open(seen_path) as f:
            return {ln.strip() for ln in f}
    return set()


def append_seen(root_dir, filepath):
    """Append file path to seen.txt."""
    with open(os.path.join(root_dir, SEEN_FILE), "a") as f:
        f.write(filepath + "\n")


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


def write_jsonl(filepath, records):
    """Append records to JSONL file."""
    with open(filepath, "a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


# --- Core ---
def get_images_from_directory(root_dir, sort_by, sort_order, load_last, filter_by):
    seen = load_seen(root_dir)
    results, added = [], set()

    if load_last:
        logging.info("Loading cached records from JSONL...")
        for rec in stream_jsonl(os.path.join(root_dir, JSONL_FILE)):
            if not rec:
                continue
            if rec["file"] in seen or rec["file"] in added:
                continue
            if not os.path.isfile(rec["file"]):
                continue
            if rec.get("suggestedName", "_") != filter_by and filter_by != "_":
                continue

            results.append(rec)
            sNames.append(rec.get("givenName", rec.get("suggestedName", "-")))
            added.add(rec["file"])
            if len(results) > 10000:
                break
    else:
        query = {
            "filetype": "image",
            "removed": False,
            "viewed": False,
            "filefullpath": {"$regex": root_dir},
        }
        cursor = list(
            db["files"].find(query, {"_id": 1, "filehash": 1, "filefullpath": 1}).sort("filesize", 1)
        )

        logging.info(f"Found {len(cursor)} files in Mongo")

        batch = []
        for doc in tqdm(cursor, unit="img"):
            img_path = doc["filefullpath"]
            if not os.path.isfile(img_path):
                continue

            props = db["filesLookup"].find_one({"_id": doc["filehash"]})
            rec = {"file": img_path}

            if props and props.get("props"):
                pr = props["props"]
                rec.update({
                    "w": pr.get("width", 0),
                    "h": pr.get("height", 0),
                    "pixels": pr.get("width", 0) * pr.get("height", 0),
                    "face_area": round(pr.get("faceArea", 0), 2),
                    "skinPer": pr.get("skinPer", 0),
                    "size": int(props.get("filesize", 0)) if isinstance(props.get("filesize"), int)
                            else 0,
                    "hsize": humanize.naturalsize(props.get("filesize", 0)),
                    "mtime": props.get("filemtime", 0),
                    "nsfw_score": pr.get("specialProps", {}).get("nsfw_score", -1),
                    "scoreAvg": round(pr.get("specialProps", {}).get("scoreAvg", -1), 2),
                })

                # Suggested names
                rec["suggestedName"] = props.get("givenName", props.get("suggestedName", "-"))
                sNames.append(rec["suggestedName"])

                # Exposed labels
                vals, top_label, top_score = [], "NaN", -1e6
                for lbl in EXPOSED_LABELS:
                    val = pr.get("specialProps", {}).get(lbl)
                    if val is not None:
                        rec[lbl] = val
                        vals.append(val)
                        if val > top_score:
                            top_label, top_score = lbl, val
                rec["exposedScore"] = max(vals) if vals else 0
                rec["topExposedLabel"] = f"{top_label}_{round(top_score,2)}"
            else:
                try:
                    with Image.open(img_path) as im:
                        w, h = im.size
                except Exception:
                    w, h = 0, 0
                size = os.path.getsize(img_path)
                rec.update({
                    "w": w, "h": h, "pixels": w*h, "face_area": 0,
                    "skinPer": 0, "size": size, "hsize": humanize.naturalsize(size),
                    "mtime": 0, "nsfw_score": 0, "scoreAvg": -1,
                    "suggestedName": "-", "exposedScore": 0, "topExposedLabel": "NaN"
                })

            batch.append(rec)
            if len(batch) >= 100:
                write_jsonl(os.path.join(root_dir, JSONL_FILE), batch)
                results.extend(batch)
                batch.clear()

        if batch:
            write_jsonl(os.path.join(root_dir, JSONL_FILE), batch)
            results.extend(batch)

    # Sort + paginate
    results = sorted(results, key=lambda x: x.get(sort_by, -1), reverse=sort_order)[:1000]
    final = [
        [r["file"], f"{r['w']}x{r['h']}", r["face_area"], r["hsize"],
         r["skinPer"], r["nsfw_score"], r["topExposedLabel"], r["scoreAvg"]]
        for r in results if r["file"] not in seen
    ]
    return final


# --- Flask routes ---
@app.route("/")
def index():
    sort_fields = [
        ("size", "File Size"), ("pixels", "Resolution"), ("skinPer", "skinPer"),
        ("nsfw_score", "NSFW"), ("face_area", "Face area"), ("mtime", "Ctime"),
        ("scoreAvg", "Avg Score"), ("exposedScore", "Exposed Score")
    ]
    counter = Counter(sNames)
    result = sorted([[n, c] for n, c in counter.items()], key=lambda x: x[1], reverse=True)
    return render_template("Imageindex.html", sort_fields=sort_fields, sNames=result)


@app.route("/load_images", methods=["POST"])
def load_images():
    global root_dir, loaded_images_cache
    directory = request.form.get("directory_path")
    sort_by = request.form.get("sort_by", "size")
    sort_order = request.form.get("sort_order", "asc") != "asc"
    load_last = request.form.get("loadLast") == "true"
    filter_by = request.form.get("filter_by", "-")
    page = int(request.form.get("page", 1))

    if not directory or not os.path.exists(directory):
        return jsonify({"images": [], "error": "Invalid directory"})

    root_dir = directory
    loaded_images_cache = get_images_from_directory(directory, sort_by, sort_order, load_last, filter_by)

    start, end = (page - 1) * IMAGES_PER_PAGE, page * IMAGES_PER_PAGE
    return jsonify({"images": loaded_images_cache[start:end], "total_images": len(loaded_images_cache)})


@app.route("/serve_image")
def serve_image():
    image_path = request.args.get("image_path")
    if image_path and os.path.exists(image_path):
        return send_file(image_path)
    return jsonify({"error": "Image not found"}), 400


@app.route("/keep_image", methods=["POST"])
def keep_image():
    image_path = request.form.get("image_name")
    append_seen(root_dir, image_path)
    target_dir = root_dir + "_keeped"
    os.makedirs(target_dir, exist_ok=True)
    try:
        shutil.move(image_path, os.path.join(target_dir, os.path.basename(image_path)))
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/delete_image", methods=["POST"])
def delete_image():
    image_path = request.form.get("image_name")
    if not image_path or not os.path.exists(image_path):
        return jsonify({"success": False, "error": "Image not found"}), 400
    try:
        os.remove(image_path)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/move_image", methods=["POST"])
def move_image():
    image_path = request.form.get("image_name")
    if not image_path or not os.path.exists(image_path):
        return jsonify({"success": False, "error": "Image not found"}), 400
    target_dir = root_dir + "_moved"
    os.makedirs(target_dir, exist_ok=True)
    try:
        shutil.move(image_path, os.path.join(target_dir, os.path.basename(image_path)))
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
