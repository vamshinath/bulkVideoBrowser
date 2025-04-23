import os
import shutil,sys
import humanize,json,psutil
from flask import Flask, request, jsonify, render_template, send_file
from PIL import Image
from datetime import datetime
Image.MAX_IMAGE_PIXELS = None
from filehash import FileHash
from tqdm import tqdm
import requests,string
import logging,cv2,random
import face_recognition,psutil
import numpy as np
from pymongo import MongoClient
mongoClient = MongoClient('mongodb://localhost:27017/')
db = mongoClient["filesManager"]
mp3_file = '/home/vamshi/mp3.mp3'
hasher = FileHash('sha256')



app = Flask(__name__)
IMAGES_PER_PAGE = 50
root_dir=''
def get_images_from_directory(root_dir,sortBy,sort_order,load_last):

    print(sortBy,sort_order,load_last,quick_load)
    alreadySeen = []
    try:
        with open(root_dir+"/seen.txt") as fl:
            for ln in fl:
                alreadySeen.append(ln[:-1])
    except Exception as e:
        alreadySeen=[]
    finalRec=[]

    alreadyCalc=set()
    if os.path.isfile(os.path.join(root_dir,"lastLoad.jsonl")):
        with open(os.path.join(root_dir,"lastLoad.jsonl"), "r", encoding="utf-8") as fl:
            for line in fl:
                rec = json.loads(line.strip())
                if rec:
                    try:
                        alreadyCalc.add(rec['file'])
                    except Exception as e:
                        e=0
    if load_last:
        print("loaded from json")
        with open(os.path.join(root_dir,"lastLoad.jsonl"), "r", encoding="utf-8") as fl:
            for line in fl:
                rec = json.loads(line.strip())  # Convert JSON string to dictionary
                if rec and rec['file'] not in alreadySeen and os.path.isfile(rec['file']):
                    finalRec.append(rec)


    else:
        image_files = []
        
        query = {
            "filetype": "image",
            "isReady": True,
            "filefullpath": {"$regex": root_dir}
        }

        cursor = list(db["files"].find(query, {"_id": 1, "filehash": 1, "filefullpath": 1}).sort("filesize", 1))
        ttl = len(cursor)

        print('total files',ttl)

        for img in tqdm(cursor,total=ttl,unit='img'):
            filehash=img['filehash']
            img = img['filefullpath']
            if not os.path.isfile(img):continue
            props = db['rootLookup'].find_one({'_id': filehash})

            if props and props['props']:
                rec={}
                try:
                    w=props['props']['width']
                    h=props['props']['height']

                    try:
                        face_area = props['props']['faceArea']
                    except Exception as e:
                        face_area=0

                    rec['file']=img
                    rec['w']=w
                    rec['h']=h
                    rec['pixels']=w*h
                    rec['face_area']=round(face_area,2)
                    try:
                        rec['skinPer']=props['props']['skinPer']
                    except Exception as e:
                        rec['skinPer']=0

                    rec['size']=props['filesize']
                    rec['hsize']=humanize.naturalsize(rec['size'])
                    rec['mtime']=props['filemtime']
                    try:
                        rec['nsfw_score']=props['props']['specialProps']['nsfw_score']
                    except Exception as e:
                        rec['nsfw_score']=-1

                    try:
                        rec['scoreAvg'] = round(props['props']['specialProps']['scoreAvg'],2)
                    except Exception as e:
                        rec['scoreAvg'] = -1

                    exposedLabels = ['ARMPITS_EXPOSED_score','EXPOSED_ARMPITS_score',
                         'BELLY_EXPOSED_score','EXPOSED_BELLY_score',
                         'EXPOSED_BUTTOCKS_score','BUTTOCKS_EXPOSED_score'
                         'EXPOSED_BREAST_F_score','FEMALE_BREAST_EXPOSED',
                         'FEMALE_GENITALIA_EXPOSED','EXPOSED_GENITALIA_F'
                         ]
                    
                    rec['exposedScore']= 0
                    topExposedLabel='NaN'
                    topExposedScore = -1000000
                    vals=[]
                    for label in exposedLabels:
                        try:
                            lbScore = props['props']['specialProps'][label]
                            vals.append(lbScore)
                            if topExposedScore < lbScore:
                                topExposedLabel=label
                                topExposedScore=lbScore
                        except Exception as e:
                            e=0
                    try:
                        rec['exposedScore']=max(vals)
                    except Exception as e:
                        rec['exposedScore']=0
                    rec['topExposedLabel']=topExposedLabel.split('_score')[0]+'_'+str(round(topExposedScore,2))




                except Exception as e:
                    print(e,filehash)

                with open(os.path.join(root_dir,"lastLoad.jsonl"),'a',encoding='utf-8') as fl:
                    fl.write(json.dumps(rec) + "\n") 


    preSort = sorted(finalRec,key= lambda x:x[sortBy],reverse=sort_order)
    finalList=[]
    for rec in preSort:
        finalList.append([rec['file'],str(rec['w'])+'x'+str(rec['h']),rec['face_area'],rec['hsize'],rec['skinPer'],rec['nsfw_score'],rec['topExposedLabel'],rec['scoreAvg']])
    return finalList

@app.route('/')
def index():
    return render_template('Imageindex.html')

@app.route('/load_images', methods=['GET', 'POST'])
def load_images():

    global root_dir,quick_load
    directory = request.form.get('directory_path')
    print(list(request.form.items()))
    sort_by = request.form.get('sort_by', 'size') 
    sort_order= request.form.get('sort_order', 'asc') != 'asc'
    load_last = request.form.get("loadLast") == "true"
    quick_load = request.form.get("quickLoad") == "true"


    print(sort_by,request.form.get('sort_order'),request.form.get("loadLast"),quick_load)


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

    target_dir = root_dir + "_keeped"
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

    target_dir = root_dir + "_moved"
    os.makedirs(target_dir, exist_ok=True)
    
    try:
        shutil.move(image_path, os.path.join(target_dir, os.path.basename(image_path)))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)
