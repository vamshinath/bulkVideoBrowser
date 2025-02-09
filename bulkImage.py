import os
import shutil
import humanize
from flask import Flask, request, jsonify, render_template, send_file

app = Flask(__name__)
IMAGES_PER_PAGE = 50
root_dir=''
def get_images_from_directory(root_dir):

    alreadySeen = []
    try:
        with open(root_dir+"/seen.txt") as fl:
            for ln in fl:
                alreadySeen.append(ln[:-1])
    except Exception as e:
        alreadySeen=[]


    image_files = []
    for subdir, _, files in os.walk(root_dir):
        for file in files:
            file_path = os.path.abspath(os.path.join(subdir, file))  # Ensure full path
            if file.lower().endswith(('jpg', 'jpeg', 'png', 'bmp', 'webp', 'gif')) and file_path not in alreadySeen:
                image_files.append([
                    file_path,
                    os.path.getsize(file_path),
                    os.stat(file_path).st_ctime
                ])
    return [[img, f"{humanize.naturalsize(sz)}", str(ctime)] for img, sz, ctime in sorted(image_files, key=lambda x: x[1], reverse=True)]

@app.route('/')
def index():
    return render_template('Imageindex.html')

@app.route('/load_images', methods=['POST'])
def load_images():
    global root_dir
    directory = request.form.get('directory_path')
    root_dir = directory
    page = int(request.form.get('page', 1))

    if not directory or not os.path.exists(directory):
        return jsonify({'images': [], 'error': 'Invalid directory path'})

    images = get_images_from_directory(directory)
    start_index = (page - 1) * IMAGES_PER_PAGE
    end_index = start_index + IMAGES_PER_PAGE
    images_on_page = images[start_index:end_index]

    return jsonify({'images': images_on_page, 'total_images': len(images)})

@app.route('/serve_image')
def serve_image():
    image_path = request.args.get('image_path')
    if image_path and os.path.exists(image_path):
        return send_file(image_path)
    return jsonify({'error': 'Image not found'}), 400

@app.route('/keep_image', methods=['POST'])
def keep_image():
    image_path = request.form.get('image_name')
    with open(root_dir+"/seen.txt",'a') as fl:
        fl.write(image_path+"\n")

    target_dir = os.path.dirname(root_dir) + "_keeped"
    os.makedirs(target_dir, exist_ok=True)
    
    try:
        shutil.move(image_path, os.path.join(target_dir, os.path.basename(image_path)))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/delete_image', methods=['POST'])
def delete_image():
    image_path = request.form.get('image_name')
    if not image_path or not os.path.exists(image_path):
        return jsonify({'success': False, 'error': 'Image not found'}), 400

    try:
        os.remove(image_path)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/move_image', methods=['POST'])
def move_image():
    image_path = request.form.get('image_name')
    if not image_path or not os.path.exists(image_path):
        return jsonify({'success': False, 'error': 'Image not found'}), 400

    target_dir = os.path.dirname(root_dir) + "_moved"
    os.makedirs(target_dir, exist_ok=True)
    
    try:
        shutil.move(image_path, os.path.join(target_dir, os.path.basename(image_path)))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)
