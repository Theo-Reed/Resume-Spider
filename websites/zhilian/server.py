import os
import sys
import csv
import re
from flask import Flask, request, jsonify
from flask_cors import CORS

# 确保能导入项目根目录的 util
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from util.handle_csv import save_to_csv, fieldnames, generate_job_id

app = Flask(__name__)
CORS(app)  # 允许浏览器插件跨域调用

ZHILIAN_DIR = os.path.dirname(os.path.abspath(__file__))
JOBS_META_FILE = os.path.join(ZHILIAN_DIR, "csv_file", "jobs_meta.csv")
JOBS_UPDATED_FILE = os.path.join(ZHILIAN_DIR, "csv_file", "jobs_meta_updated.csv")

@app.route('/upload_list', methods=['POST'])
def upload_list():
    data = request.json
    jobs = data.get('jobs', [])
    if jobs:
        save_to_csv(JOBS_META_FILE, jobs)
        return jsonify({"success": True, "count": len(jobs)})
    return jsonify({"success": False, "message": "No jobs provided"})

@app.route('/upload_detail', methods=['POST'])
def upload_detail():
    item = request.json
    if not item or 'source_url' not in item:
        return jsonify({"success": False, "message": "Invalid detail data"})
    
    # 1. 极其严格地清洗当前 URL，用于匹配
    def clean_url(u):
        if not u: return ""
        # 去掉协议头 (http/https)、查询参数、锚点、末尾斜杠，并转小写
        u = u.replace('https://', '').replace('http://', '')
        return u.split('?')[0].split('#')[0].strip().rstrip('/').lower()

    current_url_raw = item.get('source_url', '')
    current_url_cleaned = clean_url(current_url_raw)
    
    # 2. 从 jobs_meta.csv 中寻找原始信息，优先使用 meta 里的 ID
    meta_info = {}
    matched_job_id = None
    if os.path.exists(JOBS_META_FILE):
        try:
            with open(JOBS_META_FILE, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    row_url_cleaned = clean_url(row.get("source_url", ""))
                    if row_url_cleaned == current_url_cleaned:
                        meta_info = row
                        matched_job_id = row.get("_id")
                        break
        except Exception as e:
            print(f"读取 meta 文件出错: {e}")

    # 如果 meta 里没找到，再根据当前 URL 生成一个 ID
    job_id = matched_job_id or generate_job_id(current_url_raw)
    
    full_item = {field: "" for field in fieldnames}
    
    full_item['_id'] = job_id
    full_item['source_url'] = current_url_raw # 保持原始 URL
    full_item['source_name'] = "智联招聘"
    full_item['source_name_english'] = "Zhilian Zhaopin"
    full_item['type'] = "国内"
    full_item['is_remote'] = "1"

    raw_title = meta_info.get('title') or item.get('title') or "未知职位"
    
    salary_patterns = [
        r'\s*[\d\.\-kK]+[kK]',
        r'\s*[\d\-]+薪',
        r'\s*[\d\.\-]+元/.*',
    ]
    clean_title = raw_title
    for pattern in salary_patterns:
        clean_title = re.sub(pattern, '', clean_title)
    
    full_item['title'] = clean_title.strip()
    
    from utils import is_valid_experience, convert_salary_to_english
    for field in ['team', 'salary', 'city']:
        full_item[field] = meta_info.get(field) or item.get(field) or ""
    
    # 对薪资进行归一化处理
    full_item['salary'] = convert_salary_to_english(full_item['salary'], to_english=False)
    
    # 对经验字段进行归一化处理
    raw_exp = meta_info.get('experience') or item.get('experience') or ""
    full_item['experience'] = is_valid_experience(raw_exp)

    full_item['description'] = item.get('description') or ""
    if item.get('keywords'):
        full_item['summary'] = ",".join(item['keywords'])
    elif meta_info.get('summary'):
        full_item['summary'] = meta_info['summary']

    full_item['createdAt'] = item.get('createdAt') or meta_info.get('createdAt') or ""

    for k in full_item:
        if isinstance(full_item[k], str):
            full_item[k] = full_item[k].strip()
        
    save_to_csv(JOBS_UPDATED_FILE, [full_item])
    print(f"✅ 已同步详情: {full_item['title']} (ID: {job_id[:8]})")
    return jsonify({"success": True})

@app.route('/get_next_url', methods=['POST'])
def get_next_url():
    """改进的任务获取逻辑：无视协议头、支持双重校验"""
    def clean_url(u):
        if not u: return ""
        u = u.replace('https://', '').replace('http://', '')
        return u.split('?')[0].split('#')[0].strip().rstrip('/').lower()

    processed_keys = set()
    if os.path.exists(JOBS_UPDATED_FILE):
        try:
            with open(JOBS_UPDATED_FILE, "r", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    jid = row.get("_id")
                    url = clean_url(row.get("source_url"))
                    if jid: processed_keys.add(jid)
                    if url: processed_keys.add(url)
        except Exception as e:
            print(f"读取已处理文件出错: {e}")
    
    if os.path.exists(JOBS_META_FILE):
        try:
            with open(JOBS_META_FILE, "r", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    job_id = row.get("_id")
                    raw_url = row.get("source_url")
                    url = clean_url(raw_url)
                    
                    if job_id in processed_keys or url in processed_keys:
                        continue
                    
                    print(f"🎯 智联：派发下一个任务 -> {raw_url}")
                    return jsonify({"success": True, "url": raw_url})
        except Exception as e:
            print(f"读取 meta 文件出错: {e}")
    
    print("🏁 智联招聘：所有详情页已同步完成")
    return jsonify({"success": True, "url": None})

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🚀 智联招聘 Bridge Server 已启动")
    print("地址: http://127.0.0.1:5001")
    print("="*60 + "\n")
    app.run(host='0.0.0.0', port=5001, debug=False)
