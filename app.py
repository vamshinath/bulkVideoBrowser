from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file
import os
import humanize

import cv2,json

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
        tmp = json.load(open(lastLoadFile))
        videos=[]
        for rec in tmp:
            if rec['path'] not in ok_videos and os.path.isfile(rec['path']):
                videos.append(rec)
    else:
        for root, _, files in os.walk(directory):
            for file in files:
                file_path = os.path.join(root, file)
                if os.path.splitext(file)[1].lower() in video_exts and file_path not in ok_videos:
                    file_size = os.path.getsize(file_path)  # Convert to MB
                    width=height=0
                    seconds=1
                    ctime = os.stat(file_path).st_mtime
                    if sort_by =='resolution' or True:
                        try:
                            cap = cv2.VideoCapture(file_path)
                            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                            fps = cap.get(cv2.CAP_PROP_FPS)
                            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                            duration = frame_count/fps
                            seconds = round(duration,2)
                            cap.release()
                        except Exception as e:
                            e=0
                    else:
                        width=height=0


                    resolution = f"{width}x{height}"
                    
                    videos.append({"path": file_path,'ctime':ctime,"size": file_size,"seconds":seconds,"szbydur":round(file_size/max(seconds,1),2)
                                ,"resolution": resolution,"width": width, "height": height,"sortField":sort_by})
                
    if sort_by == "resolution":
        videos.sort(key=lambda x: (x["width"]* x["height"]),reverse=sort_order)  # Sort by WxH (smallest first)
    elif sort_by == "size":
        videos.sort(key=lambda x: x["size"],reverse=sort_order)
    elif sort_by == "seconds":
        videos.sort(key=lambda x: x["seconds"],reverse=sort_order)
    elif sort_by == "szbydur":
        videos.sort(key=lambda x: x["szbydur"],reverse=sort_order)
    elif sort_by == "ctime":
        videos.sort(key=lambda x: x["ctime"],reverse=sort_order)

    
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
