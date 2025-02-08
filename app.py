from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file
import os
import humanize

import cv2

app = Flask(__name__)
sort_by='size'
session={}

def get_videos(directory,sort_by):
    video_exts = {".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv"}
    videos = []

    # Path to okList.txt
    ok_list_path = os.path.join(directory, 'okList.txt')
    ok_videos = set()

    # Read already "OK" videos if okList.txt exists
    if os.path.exists(ok_list_path):
        with open(ok_list_path, 'r') as f:
            ok_videos = set(line.strip() for line in f.readlines())

    # Collect videos, skipping those in okList.txt
    for root, _, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            if os.path.splitext(file)[1].lower() in video_exts and file_path not in ok_videos:
                file_size = os.path.getsize(file_path)  # Convert to MB

                try:
                    cap = cv2.VideoCapture(file_path)
                    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    cap.release()
                except Exception as e:
                    width=height=0

                resolution = f"{width}x{height}"
                
                videos.append({"path": file_path, "size": file_size, "resolution": resolution,"width": width, "height": height})
                
    if sort_by == "resolution":
        videos.sort(key=lambda x: (x["width"]* x["height"]),reverse=True)  # Sort by WxH (smallest first)
    else:
        videos.sort(key=lambda x: x["size"],reverse=True)

    return videos


@app.route('/serve_video')
def serve_video():
    video_path = request.args.get('path')
    if video_path and os.path.exists(video_path):
        return send_file(video_path, mimetype='video/mp4')
    return "File not found", 404

@app.route('/', methods=['GET', 'POST'])
def index():
    global sort_by,session
    session={}
    if request.method == 'POST':
        directory = request.form['directory']
        sort_by = request.form.get('sort_by', 'size')  # Default to 'size' if not provided
        return redirect(url_for('videos', directory=directory, sort_by=sort_by))
    return render_template('index.html')

@app.route('/videos')
def videos():
    global session
    directory = request.args.get('directory', '')
    sort_by = request.args.get('sort_by', 'size') 

    if not os.path.isdir(directory):
        return "Invalid directory path", 400
    video_list = get_videos(directory,sort_by)

    session["videos"] = video_list
    session["removed_videos"] = set()  # Store removed videos


    return render_template('videos.html', videos=video_list[:10], directory=directory)

@app.route('/ok', methods=['POST'])
def mark_ok():
    data = request.json
    video_path = data.get('video')
    directory = data.get('directory', '')

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
    video_path = request.json.get('video')
    directory = request.json.get('directory', '')
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
        if video["path"] not in removed_videos:
            return video

    return None  # No more videos left

if __name__ == '__main__':
    app.run('0.0.0.0',port=9898)
