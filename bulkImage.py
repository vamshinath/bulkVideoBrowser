import os
import shutil,sys
import humanize,json,psutil
from flask import Flask, request, jsonify, render_template, send_file
from PIL import Image
from datetime import datetime
Image.MAX_IMAGE_PIXELS = None

from transformers import pipeline
import requests,string
import logging,cv2,random
import face_recognition
import numpy as np
from cvzone.SelfiSegmentationModule import SelfiSegmentation
segmentor = SelfiSegmentation()
mp3_file = '/home/vamshi/mp3.mp3'


logging.getLogger("transformers").setLevel(logging.ERROR)


def faceArea(fl):
    try:
        total_pixels = Image.open(fl).size
        faceimage = face_recognition.load_image_file(fl)
        dim = face_recognition.face_locations(faceimage)[0]
        area = abs(dim[3]-dim[1])*abs(dim[0]-dim[2])
        face_area = area/(total_pixels[0]*total_pixels[1])*100
    except Exception as e:
        face_area=0
    return face_area


def findPer2(imagepath,removeBG=True):
    img=cv2.imread(imagepath)
    total_pixels = Image.open(imagepath).size
    total_pixels = total_pixels[0]*total_pixels[1]
    flnmtmp = ''.join(random.choices(string.ascii_lowercase +string.digits, k=7))
    if removeBG:
    
        tmpbgimg = segmentor.removeBG(img)
        impath = os.path.dirname(imagepath)
        cv2.imwrite(impath+"/"+flnmtmp+'.jpg',tmpbgimg)
        img = cv2.imread(impath+"/"+flnmtmp+'.jpg')

        os.remove(impath+"/"+flnmtmp+'.jpg')
        
    #converting from gbr to hsv color space
    img_HSV = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    #skin color range for hsv color space 
    HSV_mask = cv2.inRange(img_HSV, (0, 15, 0), (17,170,255)) 
    HSV_mask = cv2.morphologyEx(HSV_mask, cv2.MORPH_OPEN, np.ones((3,3), np.uint8))

    #converting from gbr to YCbCr color space
    img_YCrCb = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb)
    #skin color range for hsv color space 
    YCrCb_mask = cv2.inRange(img_YCrCb, (0, 135, 85), (255,180,135)) 
    YCrCb_mask = cv2.morphologyEx(YCrCb_mask, cv2.MORPH_OPEN, np.ones((3,3), np.uint8))

    #merge skin detection (YCbCr and hsv)
    global_mask=cv2.bitwise_and(YCrCb_mask,HSV_mask)
    global_mask=cv2.medianBlur(global_mask,3)
    global_mask = cv2.morphologyEx(global_mask, cv2.MORPH_OPEN, np.ones((4,4), np.uint8))


    hsvCount = cv2.countNonZero(HSV_mask)
    ycrCount = cv2.countNonZero(YCrCb_mask)
    gloCount = cv2.countNonZero(global_mask)

    blackCount = [hsvCount,ycrCount,gloCount]


    avgNon=-1
    if abs(blackCount[0] - blackCount[1]) < abs(blackCount[1] - blackCount[2]) and abs(blackCount[0] - blackCount[1]) < abs(blackCount[0] - blackCount[2]):
        avgNon = (blackCount[0]+blackCount[1])/2
        #print("0,1",imagepath)
    elif abs(blackCount[1] - blackCount[2]) < abs(blackCount[0] - blackCount[1])  and abs(blackCount[1] - blackCount[2]) < abs(blackCount[0] - blackCount[2]):
        avgNon = (blackCount[1]+blackCount[2])/2
        #print("1,2",imagepath)
        
    elif abs(blackCount[0] - blackCount[2]) < abs(blackCount[1] - blackCount[2]) and abs(blackCount[0] - blackCount[2]) < abs(blackCount[0] - blackCount[1]):
        avgNon = (blackCount[0]+blackCount[2])/2
        #print("0,2",imagepath)


    ct=0
    avnn=0
    for  vl in blackCount:
        if vl < 1000:
            continue
        ct+=1
        avnn+=vl


    if ct==1:
        avgNon = avnn
    elif ct==2:
        avgNon = avnn/2


    if avgNon == -1 and removeBG:
        return findPer2(imagepath,removeBG=False)
        
    skinPercentage = avgNon*100/total_pixels


    if 100 - skinPercentage > 99.000 and removeBG:
        print(100 - skinPercentage)
        return findPer2(imagepath,removeBG=False)


    return round(skinPercentage,3)


def classify_nsfw(image_path):
    predict = pipeline("image-classification", model="AdamCodd/vit-base-nsfw-detector")
    try:
        img = Image.open(image_path)
        result = predict(img)
        return result
    except Exception as e:
        print(f"Error processing {image_path}: {e}")
        return None
    

def getNSFWScoreJS(file_path,in_memory_file=False):
    url = "http://0.0.0.0:3333/single/multipart-form"
    if in_memory_file:
        return 0
        in_memory_file.seek(0)
         
        files = {"content": ("temp.jpg", in_memory_file, "image/jpeg")}
    
    try:
        rsp = requests.get(url,timeout=3)
    except Exception as e:
        os.system(f"mpg123 {mp3_file}")
        print('Error',e)


    files = {"content": open(file_path, "rb")}
    response = requests.post(url, files=files)
    jsResponsee = sorted(response.json()['prediction'],key=lambda x:x['probability'],reverse=True)[0]
    if jsResponsee['className'] in ['Sexy','Porn']:
        jsScore = round(jsResponsee['probability'],4)
    else:
        jsScore=-1
    return jsScore

def isMemAvailable():
    return psutil.virtual_memory().available > 1173549056

def getNSFWScore(img1):
    NJsScore = getNSFWScoreJS(img1)
    addmCod = classify_nsfw(img1)
    nsfw_score = [item['score'] for item in addmCod if item['label'] == 'nsfw'][0]
    return round((nsfw_score+NJsScore)/2,4)



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

    alreadyCalc=set()
    if os.path.isfile(os.path.join(root_dir,"lastLoad.jsonl")):
        with open(os.path.join(root_dir,"lastLoad.jsonl"), "r", encoding="utf-8") as fl:
            for line in fl:
                rec = json.loads(line.strip())
                try:
                    alreadyCalc.add(rec['file'])
                except Exception as e:
                    e=0


    if load_last:
        print("loaded from json")
        with open(os.path.join(root_dir,"lastLoad.jsonl"), "r", encoding="utf-8") as fl:
            for ctr,line in enumerate(fl):
                rec = json.loads(line.strip())  # Convert JSON string to dictionary
                print(ctr)
                if rec['file'] not in alreadySeen and os.path.isfile(rec['file']):
                    finalRec.append(rec)


    else:
        image_files = []
        for subdir, _, files in os.walk(root_dir):
            for file in files:
                file_path = os.path.abspath(os.path.join(subdir, file))  # Ensure full path
                if file_path in alreadyCalc:continue
                if file.lower().endswith(('jpg', 'jpeg', 'png', 'bmp', 'webp', 'gif')) and file_path not in alreadySeen:
                    image_files.append([
                        file_path,
                        os.path.getsize(file_path),
                        os.stat(file_path).st_mtime
                    ])

        finalRec=[]
        ctr=0
        ttl = len(image_files)
        image_files = sorted(image_files,key=lambda x:x[1],reverse=True)

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
                try:
                    skinPer = findPer2(img)
                except Exception as e:
                    print(e)
                try:
                    nsfw_score1 = getNSFWScore(img)
                except Exception as e:
                    print(e)

                rec['skinPer']=skinPer
                rec['nsfw_score']=nsfw_score1
                #finalRec.append(rec)
            except Exception as e:
                print(e)

            with open(os.path.join(root_dir,"lastLoad.jsonl"),'a',encoding='utf-8') as fl:
                fl.write(json.dumps(rec) + "\n") 
            
            if ctr%5:
                if not isMemAvailable():
                    print("Memory full,exiting")
                    os.system(f"mpg123 {mp3_file}")
                    sys.exit(0)

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
