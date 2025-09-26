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
import pickle,time,string
import face_recognition
from bson.binary import Binary
from collections import Counter
mongoClient = MongoClient('mongodb://localhost:27017/')
db = mongoClient["filesLookup"]
mp3_file = '/home/vamshi/mp3.mp3'
hasher = FileHash('sha256')



app = Flask(__name__)

# === Config ===
IMAGES_PER_PAGE = 50
JSONL_FILE = "lastLoad.jsonl"
SEEN_FILE = "seen.txt"

root_dir=''
sNames=[
    '_'
]

dbimg = mongoClient["filesLookup"]
loaded_images_cache = None
page=0



units = {"B": 1, "KB": 10 ** 3, "MB": 10 ** 6, "GB": 10 ** 9, "TB": 10 ** 12}
def parse_size(size):
    number, unit = [string.strip() for string in size.split()]
    print(int(float(number)*units[unit]))
    return int(float(number)*units[unit])

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

def get_images_from_directory(root_dir,sortBy,sort_order,load_last,filter_by):

    print(sortBy,sort_order,load_last,quick_load)
    alreadySeen = load_seen(root_dir)
    finalRec,added = [], set()

    if load_last:
        ctr=0
        print("loading from json")
        for rec in tqdm(stream_jsonl(os.path.join(root_dir, JSONL_FILE)), desc="Loading JSONL"):
            if not rec:
                continue
            if rec["file"] in alreadySeen or rec["file"] in added:
                continue
            if not os.path.isfile(rec["file"]):
                continue
            if rec.get("suggestedName", "_") != filter_by and filter_by != "_":
                continue

            finalRec.append(rec)
            sNames.append(rec.get("givenName", rec.get("suggestedName", "-")))
            added.add(rec["file"])
            # if len(finalRec) > 10000:
            #     break
    else:
        image_files = []
        
        query = {
            "filetype": "image",
            "removed": False,
            "viewed":False,
            "filefullpath": {"$regex": root_dir}
        }

        cursor = list(db["files"].find(query, {"_id": 1, "filehash": 1, "filefullpath": 1}).sort("filesize", 1))
        ttl = len(cursor)

        print('total files',ttl)
        batch=[]
        for img in tqdm(cursor,total=ttl,unit='img'):
            filehash=img['filehash']
            img = img['filefullpath']
            if not os.path.isfile(img):continue
            props = db['filesLookup'].find_one({'_id': filehash})
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

                    

                    if type(props["filesize"]) == str:
                        rec["size"] = parse_size(props["filesize"].upper())
                    else:rec['size']=props['filesize']
                    
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

                    
                    try:
                        sName= props.get('givenName',props.get('suggestedName','-'))
                        sNames.append(sName)
                        rec['suggestedName'] = sName
                    except Exception as e:
                        rec['suggestedName'] = -1

                    

                    exposedLabels = ['ARMPITS_EXPOSED_score','EXPOSED_ARMPITS_score',
                         'BELLY_EXPOSED_score','EXPOSED_BELLY_score',
                         'EXPOSED_BUTTOCKS_score','BUTTOCKS_EXPOSED_score',
                         'EXPOSED_BREAST_F_score','FEMALE_BREAST_EXPOSED',
                         'FEMALE_GENITALIA_EXPOSED','EXPOSED_GENITALIA_F'
                         ]
                    exposedLabels.extend(
                        [
                            'ARMPITS_COVERED_area'
                            'ARMPITS_COVERED_score',
                            'ARMPITS_EXPOSED_area',
                            'ARMPITS_EXPOSED_score',
                            'BELLY_COVERED_area',
                            'BELLY_COVERED_score',
                            'BELLY_EXPOSED_area',
                            'BELLY_EXPOSED_score',
                            'BUTTOCKS_COVERED_area',
                            'BUTTOCKS_COVERED_score',
                            'BUTTOCKS_EXPOSED_area',
                            'BUTTOCKS_EXPOSED_score',
                            'COVERED_BELLY_area',
                            'COVERED_BELLY_score',
                            'COVERED_BREAST_F_area',
                            'COVERED_BREAST_F_score',
                            'COVERED_BUTTOCKS_area',
                            'COVERED_BUTTOCKS_score',
                            'COVERED_GENITALIA_F_area',
                            'COVERED_GENITALIA_F_score',
                            'EXPOSED_ARMPITS_area',
                            'EXPOSED_ARMPITS_score',
                            'EXPOSED_BELLY_area',
                            'EXPOSED_BELLY_score',
                            'EXPOSED_BREAST_F_area',
                            'EXPOSED_BREAST_F_score',
                            'EXPOSED_BUTTOCKS_area',
                            'EXPOSED_BUTTOCKS_score',
                            'EXPOSED_GENITALIA_F_area',
                            'EXPOSED_GENITALIA_F_score',
                            'FEMALE_BREAST_COVERED_area',
                            'FEMALE_BREAST_COVERED_score',
                            'FEMALE_BREAST_EXPOSED_area',
                            'FEMALE_BREAST_EXPOSED_score',
                            'FEMALE_GENITALIA_COVERED_area',
                            'FEMALE_GENITALIA_COVERED_score',
                            'FEMALE_GENITALIA_EXPOSED_area',
                            'FEMALE_GENITALIA_EXPOSED_score'
                        ]
                    )
                    
                    rec['exposedScore']= 0
                    topExposedLabel='NaN'
                    topExposedScore = -1000000
                    vals=[]
                    for label in exposedLabels:
                        try:
                            lbScore = props['props']['specialProps'][label]
                            rec[label]=lbScore
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
                # try:
                #     with open(os.path.join(root_dir,"lastLoad.jsonl"),'a',encoding='utf-8') as fl:
                #         fl.write(json.dumps(rec) + "\n") 
                # except Exception as e:
                #     e=0
            else:
                w=h=pixels=0
                try:
                    with Image.open(img) as imge:
                        w,h = imge.size
                        pixels = w*h
                except Exception as e:e=0

                size = os.path.getsize(img)
                rec={"file": img, "w": w, "h": h, "pixels": pixels, "face_area": 0, "skinPer": 0, 
                "size": size, "hsize": humanize.naturalsize(size), "mtime": props['filemtime'], "nsfw_score": 0, 
                "scoreAvg": -1, "suggestedName": "-", "exposedScore": 0, "topExposedLabel": "NaN"}

                # with open(os.path.join(root_dir,"lastLoad.jsonl"),'a',encoding='utf-8') as fl:
                #     fl.write(json.dumps(rec) + "\n")
            
            batch.append(rec)
            if len(batch) >= 100:
                write_jsonl(os.path.join(root_dir, JSONL_FILE), batch)
                finalRec.extend(batch)
                batch.clear()
        if batch:
            write_jsonl(os.path.join(root_dir, JSONL_FILE), batch)
            finalRec.extend(batch)
            batch.clear()
        

    preSort = sorted(finalRec,key= lambda x:x.get(sortBy,-1),reverse=sort_order)
    finalList=[]
    addedList=set()
    for rec in preSort:
        if rec['file'] not in addedList:
            addedList.add(rec['file'])
            finalList.append([rec['file'],str(rec['w'])+'x'+str(rec['h']),rec['face_area'],rec['hsize'],rec['skinPer'],rec['nsfw_score'],rec['topExposedLabel'],rec['scoreAvg']])
    return finalList

@app.route('/')
def index():

    sort_fields = [
        ("size", "File Size"),
        ("pixels", "Resolution (WxH)"),
        ("skinPer", "skinPer"),
        ("nsfw_score", "nsfw_score"),
        ("face_area", "Face area"),
        ("mtime", "Ctime"),
        ("scoreAvg", "scoreAvg"),
        ("exposedScore", "exposedScore"),
        ('ARMPITS_COVERED_area','ARMPITS_COVERED_area'),
        ('ARMPITS_COVERED_score','ARMPITS_COVERED_score'),
        ('ARMPITS_EXPOSED_area','ARMPITS_EXPOSED_area'),
        ('ARMPITS_EXPOSED_score','ARMPITS_EXPOSED_score'),
        ('BELLY_COVERED_area','BELLY_COVERED_area'),
        ('BELLY_COVERED_score','BELLY_COVERED_score'),
        ('BELLY_EXPOSED_area','BELLY_EXPOSED_area'),
        ('BELLY_EXPOSED_score','BELLY_EXPOSED_score'),
        ('BUTTOCKS_COVERED_area','BUTTOCKS_COVERED_area'),
        ('BUTTOCKS_COVERED_score','BUTTOCKS_COVERED_score'),
        ('BUTTOCKS_EXPOSED_area','BUTTOCKS_EXPOSED_area'),
        ('BUTTOCKS_EXPOSED_score','BUTTOCKS_EXPOSED_score'),
        ('COVERED_BELLY_area','COVERED_BELLY_area'),
        ('COVERED_BELLY_score','COVERED_BELLY_score'),
        ('COVERED_BREAST_F_area','COVERED_BREAST_F_area'),
        ('COVERED_BREAST_F_score','COVERED_BREAST_F_score'),
        ('COVERED_BUTTOCKS_area','COVERED_BUTTOCKS_area'),
        ('COVERED_BUTTOCKS_score','COVERED_BUTTOCKS_score'),
        ('COVERED_GENITALIA_F_area','COVERED_GENITALIA_F_area'),
        ('COVERED_GENITALIA_F_score','COVERED_GENITALIA_F_score'),
        ('EXPOSED_ARMPITS_area','EXPOSED_ARMPITS_area'),
        ('EXPOSED_ARMPITS_score','EXPOSED_ARMPITS_score'),
        ('EXPOSED_BELLY_area','EXPOSED_BELLY_area'),
        ('EXPOSED_BELLY_score','EXPOSED_BELLY_score'),
        ('EXPOSED_BREAST_F_area','EXPOSED_BREAST_F_area'),
        ('EXPOSED_BREAST_F_score','EXPOSED_BREAST_F_score'),
        ('EXPOSED_BUTTOCKS_area','EXPOSED_BUTTOCKS_area'),
        ('EXPOSED_BUTTOCKS_score','EXPOSED_BUTTOCKS_score'),
        ('EXPOSED_GENITALIA_F_area','EXPOSED_GENITALIA_F_area'),
        ('EXPOSED_GENITALIA_F_score','EXPOSED_GENITALIA_F_score'),
        ('FEMALE_BREAST_COVERED_area','FEMALE_BREAST_COVERED_area'),
        ('FEMALE_BREAST_COVERED_score','FEMALE_BREAST_COVERED_score'),
        ('FEMALE_BREAST_EXPOSED_area','FEMALE_BREAST_EXPOSED_area'),
        ('FEMALE_BREAST_EXPOSED_score','FEMALE_BREAST_EXPOSED_score'),
        ('FEMALE_GENITALIA_COVERED_area','FEMALE_GENITALIA_COVERED_area'),
        ('FEMALE_GENITALIA_COVERED_score','FEMALE_GENITALIA_COVERED_score'),
        ('FEMALE_GENITALIA_EXPOSED_area','FEMALE_GENITALIA_EXPOSED_area'),
        ('FEMALE_GENITALIA_EXPOSED_score','FEMALE_GENITALIA_EXPOSED_score')
    ]

    counter = Counter(sNames)
    result = [[name, count] for name, count in counter.items()]
    result.sort(key=lambda x:x[1],reverse=True)
    return render_template('Imageindex.html',sort_fields=sort_fields,sNames=result)

@app.route('/load_images', methods=['GET', 'POST'])
def load_images():

    global root_dir,quick_load,loaded_images_cache,page
    directory = request.form.get('directory_path')
    print(list(request.form.items()))
    sort_by = request.form.get('sort_by', 'size') 
    sort_order= request.form.get('sort_order', 'asc') != 'asc'
    load_last = request.form.get("loadLast") == "true"
    quick_load = request.form.get("quickLoad") == "true"
    filter_by = request.form.get('filter_by', '-') 


    print(sort_by,request.form.get('sort_order'),request.form.get("loadLast"),quick_load,filter_by)


    root_dir = directory
    page = page+1#int(request.form.get('page', 1))

    print("page:",page)

    if not directory or not os.path.exists(directory):
        return jsonify({'images': [], 'error': 'Invalid directory path'})

    if loaded_images_cache is None:
        print("first load")
        loaded_images_cache = get_images_from_directory(
            directory, sort_by, sort_order, load_last, filter_by
        )

    start_index = (page - 1) * IMAGES_PER_PAGE
    end_index = start_index + IMAGES_PER_PAGE
    images_on_page = loaded_images_cache[start_index:end_index]

    return jsonify({'images': images_on_page, 'total_images': len(loaded_images_cache)})

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
