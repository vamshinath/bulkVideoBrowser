from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file
import os,shutil
import humanize
from pymongo import MongoClient
mongoClient = MongoClient('mongodb://localhost:27017/')
db = mongoClient["filesLookup"]
import cv2,json
from filehash import FileHash
from tqdm import tqdm
hasher = FileHash('sha256')
app = Flask(__name__)
sort_by='size'
session={}
sizeSaved = 0
load_last=False

def get_videos(directory,sort_by):
    video_exts = {".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv"}
    videos = []

    lastLoadFile = os.path.join(directory,"lastLoad.json")
    print("Last Load File:",lastLoadFile)

    # Path to okList.txt
    ok_list_path = os.path.join(directory, 'okList.txt')
    ok_videos = set()

    # Read already "OK" videos if okList.txt exists
    if os.path.exists(ok_list_path):
        with open(ok_list_path, 'r') as f:
            ok_videos = set(line.strip() for line in f.readlines())

    if load_last:
        print("Loading from last load file")
        tmp = json.load(open(lastLoadFile))
        videos=[]
        for rec in tmp:
            if rec['path'] not in ok_videos and os.path.isfile(rec['path']):
                videos.append(rec)
        print(f"Loaded {len(videos)} videos after filtering OK list")
    else:

        query = {
            "filetype": "video",
            "isReady": True,
            "filefullpath": {"$regex": directory},
            "removed":False
        }
        video_files=[]

        print(query)

        cursor = list(db["files"].find(query, {"_id": 1, "filehash": 1, "filefullpath": 1}).sort("filesize", 1))
        
        finalRec=[]
        ctr=0
        ttl = len(cursor)

        print('total files',ttl)

        for img in tqdm(cursor,total=ttl,unit='vid'):
            filepath,filehash = img['filefullpath'],img['filehash']
            props = db['filesLookup'].find_one({'_id':filehash,'filefullpath':filepath})
            try:
                if props and props.get('props') and os.path.isfile(props['filefullpath']) and filepath not in ok_videos:
                    width = props['props']['width']
                    height = props['props']['height']

                    resolution = f"{width}x{height}"
                    videos.append({"path": props['filefullpath'],'ctime':props['filectime'],"size": props['filesize']
                                ,"seconds":props['props']['duration'],
                                "szbydur":round(props['filesize']/max(props['props']['duration'],1),2),
                                'nsfw_score':0#props['props']['nsfw_score']
                        ,"resolution": resolution,"width": width, "height": height,"sortField":sort_by})
                else:
                    videos.append({"path": props['filefullpath'],'ctime':0,"size": os.path.getsize(img['filefullpath'])
                                ,"seconds":0,
                                "szbydur":0,
                                'nsfw_score':0#props['props']['nsfw_score']
                        ,"resolution": 0,"width": 0, "height": 0,"sortField":sort_by})
            except Exception as e:
                videos.append({"path":filepath ,'ctime':0,"size": os.path.getsize(img['filefullpath'])
                                ,"seconds":0,
                                "szbydur":0,
                                'nsfw_score':0#props['props']['nsfw_score']
                        ,"resolution": 0,"width": 0, "height": 0,"sortField":sort_by})



    if sort_by == "score" and videos:
        max_duration = max(v["seconds"] for v in videos if v["seconds"]) or 1
        max_resolution = max(v["width"] * v["height"] for v in videos) or 1
        max_bitrate = max((v["size"] / max(v["seconds"], 1)) for v in videos) or 1

        for v in videos:
            duration = v["seconds"]
            resolution = v["width"] * v["height"]
            bitrate = v["size"] / max(duration, 1)

            norm_duration = duration / max_duration
            norm_resolution = resolution / max_resolution
            norm_bitrate = bitrate / max_bitrate

            # Realistic weights: duration 0.4, resolution 0.4, bitrate 0.2
            v["score"] = norm_duration * 0.4 + norm_resolution * 0.4 + norm_bitrate * 0.2

        videos.sort(key=lambda x: x["score"], reverse=sort_order)

    elif sort_by == "resolution":
        videos.sort(key=lambda x: (x["width"]* x["height"]),reverse=sort_order)  # Sort by WxH (smallest first)
    elif sort_by == "size":
        videos.sort(key=lambda x: x["size"],reverse=sort_order)
    elif sort_by == "seconds":
        videos.sort(key=lambda x: x["seconds"],reverse=sort_order)
    elif sort_by == "szbydur":
        videos.sort(key=lambda x: x["szbydur"],reverse=sort_order)
    elif sort_by == "ctime":
        videos.sort(key=lambda x: x["ctime"],reverse=sort_order)
    elif sort_by == "nsfw_score":
        videos.sort(key=lambda x: x["nsfw_score"],reverse=sort_order)

    
    with open(lastLoadFile,"w") as fl:
        json.dump(videos,fl,indent=4)

    return videos


@app.route('/serve_video')
def serve_video():
    video_path = request.args.get('path')
    if video_path and os.path.exists(video_path):
        return send_file(video_path, mimetype='video/mp4')
    return "File not found", 404

@app.route('/', methods=['GET', 'POST'])
def index():
    global sort_by,session,sort_order,load_last
    session={}
    if request.method == 'POST':
        directory = request.form['directory']
        sort_by = request.form.get('sort_by', 'size')  # Default to 'size' if not provided
        sort_order= request.form.get('sort_order', 'asc') != 'asc'
        load_last = request.form.get("loadLast") == "on"
        return redirect(url_for('videos', directory=directory, sort_by=sort_by))
    return render_template('index.html')

@app.route('/videos')
def videos():
    global session
    directory = request.args.get('directory', '')
    sort_by = request.args.get('sort_by', 'size') 

    if not os.path.isdir(directory) and not load_last:
        return "Invalid directory path", 400
    video_list = get_videos(directory,sort_by)

    session["videos"] = video_list[2:]
    session["removed_videos"] = set()  # Store removed videos


    return render_template('videos.html', videos=video_list[:2], directory=directory)

@app.route('/ok', methods=['POST'])
def mark_ok():
    data = request.json
    video_path = data.get('video')
    directory = data.get('directory', '')

    exis = session.get('removed_videos',set())
    exis.add(video_path)
    session['removed_videos']=exis

    if not video_path or not directory:
        return jsonify({"status": "error"}), 400

    ok_list_path = os.path.join(directory, 'okList.txt')

    try:
        with open(ok_list_path, 'a') as f:
            f.write(video_path + '\n')

        new_video = get_next_video(directory)
        return jsonify({"status": "added", "new_video": new_video})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/delete', methods=['POST'])
def delete_video():
    global session
    video_path = request.json.get('video')
    directory = request.json.get('directory', '')

    exis = session.get('removed_videos',set())
    exis.add(video_path)
    session['removed_videos']=exis


    if video_path and os.path.exists(video_path):
        os.remove(video_path)
        return jsonify({"status": "deleted", "new_video": get_next_video(directory)})
    return jsonify({"status": "error"}), 400


@app.route('/skip', methods=['POST'])
def skip_video():
    global session
    video_path = request.json.get('video')
    directory = request.json.get('directory', '')
    
    skippedDir = os.path.join(directory,'skipped')
    if not os.path.isdir(skippedDir):os.mkdir(skippedDir)

    if not os.path.isfile(skippedDir+"/"+os.path.basename(video_path)):shutil.move(video_path,skippedDir)

    return jsonify({"status": "skipped", "new_video": get_next_video(directory)})


def get_next_video(directory):
    """Get the next available video without rescanning the directory."""
    video_list = session.get("videos", [])
    removed_videos = session.get("removed_videos", set())

    # Find the first available video not in removed list
    for video in video_list:
        if os.path.isfile(video["path"]) and video["path"] not in removed_videos:
            exis = session.get('removed_videos',set())
            exis.add(video["path"])
            session['removed_videos']=exis

            return video

    return None  # No more videos left

if __name__ == '__main__':
    app.run('0.0.0.0',port=9898)
    #app.run(debug=True)
