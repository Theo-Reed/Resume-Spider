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

# Directory setup
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JOBS_META_FILE = os.path.join(_BASE_DIR, "csv_file", "jobs_meta.csv")
JOBS_UPDATED_FILE = os.path.join(_BASE_DIR, "csv_file", "jobs_meta_updated.csv")

# Ensure directories exist
os.makedirs(os.path.dirname(JOBS_META_FILE), exist_ok=True)

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
        return u.split('?')[0].split('#')[0].strip().rstrip('/')

    current_url = clean_url(item.get('source_url', ''))
    job_id = generate_job_id(current_url)
    
    # 2. 从 jobs_meta.csv 中寻找原始信息 (Optional, mainly for backup)
    meta_info = {}
    if os.path.exists(JOBS_META_FILE):
        try:
            with open(JOBS_META_FILE, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # 同时对比 ID 和清洗后的 URL
                    row_url = clean_url(row.get("source_url", ""))
                    if row.get("_id") == job_id or row_url == current_url:
                        meta_info = row
                        break
        except Exception as e:
            print(f"读取 meta 文件出错: {e}")

    # 3. 构造完整字段，明确优先级
    full_item = {field: "" for field in fieldnames}
    
    # 默认值
    full_item['_id'] = job_id
    full_item['source_url'] = current_url
    
    # --- source_name 统一处理 ---
    full_item['source_name'] = "Wellfound"
    full_item['source_name_english'] = "Wellfound"
    full_item['type'] = "国外"
    full_item['is_remote'] = item.get('is_remote', '1')

    # --- 基础字段优先从 meta 拿，如果 meta 为空则用传入的 item ---
    # Title
    full_item['title'] = (meta_info.get('title') or item.get('title') or "Unknown Position").strip()
    
    # Other fields
    for field in ['team', 'salary', 'salary_english', 'city', 'experience', 'summary']:
        full_item[field] = meta_info.get(field) or item.get(field) or ""

    # 详情信息则必须使用插件新抓取的
    full_item['description'] = item.get('description') or ""
    if item.get('keywords'):
        full_item['summary'] = ",".join(item['keywords'])
    elif meta_info.get('summary'):
        full_item['summary'] = meta_info['summary']

    # 发布时间
    full_item['createdAt'] = item.get('createdAt') or meta_info.get('createdAt') or ""

    # 去掉所有值的两端空格
    for k in full_item:
        if isinstance(full_item[k], str):
            full_item[k] = full_item[k].strip()
        
    save_to_csv(JOBS_UPDATED_FILE, [full_item])
    print(f"✅ Synced Detail: {full_item['title']} (ID: {job_id[:8]})")
    return jsonify({"success": True})

@app.route('/get_next_url', methods=['POST'])
def get_next_url():
    """告诉插件下一个要抓取的详情页 URL"""
    processed_ids = set()
    if os.path.exists(JOBS_UPDATED_FILE):
        try:
            with open(JOBS_UPDATED_FILE, "r", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    if row.get("_id"):
                        processed_ids.add(row["_id"])
        except: pass
    
    if os.path.exists(JOBS_META_FILE):
        try:
            with open(JOBS_META_FILE, "r", encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    job_id = row.get("_id")
                    if job_id and job_id not in processed_ids:
                        return jsonify({"url": row.get("source_url")})
        except: pass
    
    return jsonify({"url": None})

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🚀 Wellfound Bridge Server Started")
    print("Address: http://127.0.0.1:5002 (or http://localhost:5002)")
    print("="*60 + "\n")
    app.run(host='0.0.0.0', port=5002, debug=False)
