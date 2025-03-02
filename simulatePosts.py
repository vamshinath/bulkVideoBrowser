import requests,datetime

import os,psutil,time

script_name = "bulkImage.py"

while True:

    for proc in psutil.process_iter(attrs=['pid', 'name', 'memory_info', 'cmdline']):
        if script_name in " ".join(proc.info['cmdline']):
            mem_info = proc.info['memory_info']
            print(mem_info.rss)
            print(f"PID: {proc.info['pid']}, RSS: {mem_info.rss / 1024**2:.2f} MB, VMS: {mem_info.vms / 1024**2:.2f} MB")


            if mem_info.rss < 999999999:
                print('found idle')
                time.sleep(10)
                url = "http://127.0.0.1:5001/load_images"

                headers = {
                    "Accept": "*/*",
                    "Accept-Language": "en-US,en;q=0.7",
                    "Connection": "keep-alive",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Origin": "http://127.0.0.1:5001",
                    "Referer": "http://127.0.0.1:5001/",
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "same-origin",
                    "Sec-GPC": "1",
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                    "X-Requested-With": "XMLHttpRequest",
                    "sec-ch-ua": '"Not(A:Brand";v="99", "Brave";v="133", "Chromium";v="133"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Linux"'
                }

                data = {
                    "directory_path": "/media/vamshi/toshiba/ranked",
                    "page": "1",
                    "sort_by": "nsfw_score",
                    "sort_order": "desc",
                    "loadLast": "false"
                }
                try:
                    response = requests.post(url, headers=headers, data=data,timeout=4)
                except Exception as e:
                    e=0

                print("Triggered post",datetime.datetime.now())
            else:
                print("Already loading files")
    
    time.sleep(300)
