import os
import shutil,sys
import humanize,json
from flask import Flask, request, jsonify, render_template, send_file
from PIL import Image
from datetime import datetime
sys.path.insert(1, '/home/vamshi/gitRepos/machineSetupRepoMain/')
from getImageProps import getScoreOnly,faceArea
from getScore import getScore
Image.MAX_IMAGE_PIXELS = None

app = Flask(__name__)
IMAGES_PER_PAGE = 50
root_dir=''
def get_images_from_directory(root_dir,sortBy,sort_order,load_last):


    print(sortBy,sort_order,load_last)


    alreadySeen = []
    try:
        with open(root_dir+"/seen.txt") as fl:
            for ln in fl:
                alreadySeen.append(ln[:-1])
    except Exception as e:
        alreadySeen=[]
    finalRec=[]
    if load_last:
        print("loaded from json")
        with open(os.path.join(root_dir,"lastLoad.jsonl"), "r", encoding="utf-8") as fl:
            for line in fl:
                rec = json.loads(line.strip())  # Convert JSON string to dictionary
                if rec['file'] not in alreadySeen and os.path.isfile(rec['file']):
                    finalRec.append(rec)


    else:
        image_files = []
        for subdir, _, files in os.walk(root_dir):
            for file in files:
                file_path = os.path.abspath(os.path.join(subdir, file))  # Ensure full path
                if file.lower().endswith(('jpg', 'jpeg', 'png', 'bmp', 'webp', 'gif')) and file_path not in alreadySeen:
                    image_files.append([
                        file_path,
                        os.path.getsize(file_path),
                        os.stat(file_path).st_mtime
                    ])

        finalRec=[]
        ctr=0
        ttl = len(image_files)

        for img,flsz,mtime in image_files:
            print(ctr,ttl)
            ctr+=1
            rec={}
            try:
                Img = Image.open(img)
                nsfw_score1=-1
                skinPer=-10
                score=-1
                w=Img.size[0]
                h=Img.size[1]

                try:
                    face_area = faceArea(img)
                except Exception as e:
                    face_area=-1
                rec['file']=img
                rec['w']=w
                rec['h']=h
                rec['pixels']=w*h
                rec['face_area']=round(face_area,2)
                rec['size']=flsz
                rec['hsize']=humanize.naturalsize(flsz)
                rec['mtime']=mtime
                tmp = getScoreOnly(img,True,True)
                if tmp:
                    skinPer = tmp['skinPer']
                    nsfw_score1 = tmp['nsfw_score1']
                rec['skinPer']=skinPer
                rec['nsfw_score']=nsfw_score1
                finalRec.append(rec)
            except Exception as e:
                print(e)

            with open(os.path.join(root_dir,"lastLoad.jsonl"),'a',encoding='utf-8') as fl:
                fl.write(json.dumps(rec) + "\n") 

    preSort = sorted(finalRec,key= lambda x:x[sortBy],reverse=sort_order)
    finalList=[]
    for rec in preSort:
        finalList.append([rec['file'],str(rec['w'])+'x'+str(rec['h']),rec['face_area'],rec['hsize'],rec['skinPer'],rec['nsfw_score']])
    return finalList

@app.route('/')
def index():
    return render_template('Imageindex.html')

@app.route('/load_images', methods=['GET', 'POST'])
def load_images():
    global root_dir
    directory = request.form.get('directory_path')
    print(list(request.form.items()))
    sort_by = request.form.get('sort_by', 'size') 
    sort_order= request.form.get('sort_order', 'asc') != 'asc'
    load_last = request.form.get("loadLast") == "true"


    print(sort_by,request.form.get('sort_order'),request.form.get("loadLast"))


    root_dir = directory
    page = int(request.form.get('page', 1))

    if not directory or not os.path.exists(directory):
        return jsonify({'images': [], 'error': 'Invalid directory path'})

    images = get_images_from_directory(directory,sort_by,sort_order,load_last)
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
