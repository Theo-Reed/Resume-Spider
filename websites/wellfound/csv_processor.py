import csv
import os
import sys
import time
import warnings
from datetime import datetime
from typing import Dict, List, Optional, Tuple

warnings.filterwarnings('ignore')

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from util.handle_csv import fieldnames, generate_job_id
from util.type import classify_job_type
from gemini_processor import get_optimized_job_info
from utils import is_valid_experience, is_valid_job_description, convert_salary_to_english

_WELLFOUND_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE = os.path.join(_WELLFOUND_DIR, "csv_file", "jobs_meta_updated.csv")
OUTPUT_FILE = os.path.join(_WELLFOUND_DIR, "csv_file", "jobs_gemini_edited.csv")
FINAL_OUTPUT_FILE = os.path.join(_WELLFOUND_DIR, "csv_file", "jobs_final.csv")
DAILY_LIMIT = 1000
DELAY_BETWEEN_JOBS = 2


def _load_processed_status() -> Tuple[set, int, Optional[str]]:
    processed_ids = set()
    today_count = 0
    start_from_id = None
    
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                job_id = row.get('_id', '')
                title_chinese = row.get('title_chinese', '').strip()
                is_remote = row.get('is_remote', '').strip()
                
                if job_id:
                    if title_chinese or is_remote == '0':
                        processed_ids.add(job_id)
                        if title_chinese:
                            today_count += 1
                    elif start_from_id is None:
                        start_from_id = job_id
    
    return processed_ids, today_count, start_from_id


def _load_output_file() -> Tuple[Dict[str, Dict], List[Dict]]:
    job_id_to_row = {}
    all_rows = []
    
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                for field in fieldnames:
                    if field not in row:
                        row[field] = ''
                
                job_id = row.get('_id', '')
                if job_id:
                    job_id_to_row[job_id] = row
                all_rows.append(row)
    
    return job_id_to_row, all_rows


def _update_output_file(job_id: str, updated_row: Dict, fieldnames_list: List[str]):
    job_id_to_row, all_rows = _load_output_file()
    
    if job_id in job_id_to_row:
        for i, row in enumerate(all_rows):
            if row.get('_id') == job_id:
                all_rows[i] = updated_row
                break
    else:
        all_rows.append(updated_row)
    
    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames_list)
        writer.writeheader()
        writer.writerows(all_rows)


def remove_duplicate_jobs(option: int = 2):
    if option == 1:
        csv_file = INPUT_FILE
    else:
        csv_file = OUTPUT_FILE
    
    if not os.path.exists(csv_file):
        print(f"❌ Output file not found: {csv_file}")
        return

    print(f"\n{'='*80}")
    print(f"FUNCTION 4: Remove duplicate and invalid jobs")
    print(f"{'='*80}\n")

    jobs = []
    with open(csv_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            for field in fieldnames:
                if field not in row:
                    row[field] = ''
            jobs.append(row)
    
    print(f"   Total jobs before cleaning: {len(jobs)}")

    seen_title_team = set()
    cleaned_jobs = []
    duplicates_removed = 0
    invalid_removed = 0
    
    for job in jobs:
        title = job.get('title', '').strip()
        team = job.get('team', '').strip()
        description = job.get('description', '').strip()
        experience = job.get('experience', '').strip()
        
        # Valid experience check
        # if not is_valid_experience(experience):
        #    invalid_removed += 1
        #    continue
        
        title_team_key = (title, team)
        is_duplicate = False
        
        if title and team and title_team_key in seen_title_team:
            is_duplicate = True
        
        if not is_duplicate:
            if title and team:
                seen_title_team.add(title_team_key)
            cleaned_jobs.append(job)
        else:
            duplicates_removed += 1
    
    print(f"   Jobs after cleaning: {len(cleaned_jobs)}")
    print(f"   Duplicates removed: {duplicates_removed}")
    print(f"   Invalid jobs removed: {invalid_removed}")
    with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(cleaned_jobs)
    
    print(f"\n✅ Cleaning completed. Saved {len(cleaned_jobs)} jobs to {csv_file}")


def process_csv():
    """
    1. 把 jobs_meta_updated 结合到 jobs_gemini_edited，然后按时间排序
    2. 遍历 jobs_gemini_edited 执行 Gemini 处理逻辑
    """
    print(f"\n{'='*80}")
    print(f"Phase 1: Merging and Sorting")
    print(f"{'='*80}\n")

    # 1. 加载现有的 gemini_edited 数据
    existing_jobs = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    jid = row.get('_id')
                    if jid:
                        # 确保所有 fieldnames 都在 row 中
                        for field in fieldnames:
                            if field not in row: row[field] = ''
                        existing_jobs[jid] = row
            print(f"📋 Loaded {len(existing_jobs)} existing jobs from {os.path.basename(OUTPUT_FILE)}")
        except Exception as e:
            print(f"⚠️ Error loading existing output file: {e}")

    # 2. 从 jobs_meta_updated 合并新数据
    new_added_count = 0
    if os.path.exists(INPUT_FILE):
        try:
            with open(INPUT_FILE, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    jid = row.get('_id')
                    if not jid:
                        source_url = row.get('source_url', '')
                        if source_url:
                            jid = generate_job_id(source_url)
                            row['_id'] = jid
                        else: continue
                    
                    # 只有不存在时才添加，保留已有的 Gemini 处理结果
                    if jid not in existing_jobs:
                        # 基本有效性检查
                        # if not row.get('description'): continue
                        # Wellfound specific check: might have empty decsription if scraped wrongly
                        
                        # 补全字段
                        for field in fieldnames:
                            if field not in row: row[field] = ''
                        
                        existing_jobs[jid] = row
                        new_added_count += 1
            print(f"📥 Added {new_added_count} new jobs from {os.path.basename(INPUT_FILE)}")
        except Exception as e:
            print(f"⚠️ Error loading updated meta file: {e}")
    else:
        print(f"❌ Input file not found: {INPUT_FILE}")

    # 3. 排序并写回
    all_jobs_list = list(existing_jobs.values())
    
    def get_sort_key(job):
        created_at = job.get('createdAt', '')
        if not created_at: return datetime.min
        try:
            return datetime.strptime(created_at, "%Y-%m-%d")
        except: return datetime.min
    
    all_jobs_list.sort(key=get_sort_key, reverse=True)

    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_jobs_list)
    print(f"✅ Merged and sorted {len(all_jobs_list)} jobs into {os.path.basename(OUTPUT_FILE)}")

    print(f"\n{'='*80}")
    print(f"Phase 2: Processing with Gemini")
    print(f"{'='*80}\n")

    processed_ids, today_count, _ = _load_processed_status()
    if today_count >= DAILY_LIMIT:
        print(f"⚠️ Daily limit ({DAILY_LIMIT}) reached. Exiting.")
        return

    print(f"📊 Progress: {today_count}/{DAILY_LIMIT}, Remaining capacity: {DAILY_LIMIT - today_count}")

    # 重新读取刚才保存的文件进行遍历处理
    processed_today = 0
    skipped = 0
    failed = 0
    today = datetime.now()

    for i, row in enumerate(all_jobs_list, 1):
        if processed_today >= DAILY_LIMIT:
            print(f"\n✅ Daily limit reached. Stopping.")
            break
        
        # --- 增加日期过期检查 ---
        created_at_str = row.get('createdAt', '').strip()
        if created_at_str:
            try:
                job_date = datetime.strptime(created_at_str, "%Y-%m-%d")
                days_diff = (today - job_date).days
                if days_diff > 30: # Wellfound jobs might be older, using 30 days
                    # print(f"\n🛑 Job is older than 30 days ({created_at_str}), skipping.")
                    # continue # Do not stop, just skip? Or stop. Let's skip for now.
                    pass
            except Exception:
                pass 
        
        job_id = row.get('_id', '')
        # 如果已经标记为非远程，跳过
        if row.get('is_remote') == '0':
            skipped += 1
            continue
            
        # 如果已经有了翻译结果，跳过
        if row.get('title_chinese') and row.get('description_chinese'):
            skipped += 1
            continue
            
        # 描述过短或无效，跳过
        description = row.get('description', '')
        is_valid, _ = is_valid_job_description(description)
        if not is_valid:
            # skipped += 1
            # continue
            pass # Relaxed for Wellfound

        print(f"[{i}/{len(all_jobs_list)}] Processing: {row.get('title', 'N/A')[:50]}")
        
        try:
            result = get_optimized_job_info(row.get('title', ''), row.get('description', ''))
        except Exception as e:
            if "User location is not supported" in str(e):
                print(f"\n🛑 Stopped: API location error. Please switch your VPN and try again.")
                return # Exit the function completely
            print(f"    ⚠️ Warning: Gemini call failed: {e}")
            result = None
        
        if not result:
            # Check if it was a real non-remote job (empty dict) or just a failure (None)
            if result == {}:
                # 标记为非远程，避免重复处理
                row['is_remote'] = '0'
                _update_output_file(job_id, row, fieldnames)
                processed_today += 1
                print(f"    ⏭️ Marked as non-remote (Gemini returned empty)")
                continue
            else:
                # failure, just skip to next for now without marking
                skipped += 1
                continue

        # 更新字段
        row['title_chinese'] = result.get('title_chinese', '')
        row['title_english'] = result.get('title_english', '')
        row['description_chinese'] = result.get('description_chinese', '')
        row['description_english'] = result.get('description_english', '')
        
        # Tags/Summary formatting
        tags_cn = result.get('tags_chinese', [])
        tags_en = result.get('tags_english', [])
        
        if isinstance(tags_cn, list) and tags_cn:
            row['summary_chinese'] = ",".join(tags_cn)
            row['summary'] = row['summary_chinese'] # Also set summary
        if isinstance(tags_en, list) and tags_en:
            row['summary_english'] = ",".join(tags_en)
        
        # Ensure 'tags' key is not in the row (redundant but safe)
        if 'tags' in row:
            del row['tags']
        
        # 更新数据库/CSV
        _update_output_file(job_id, row, fieldnames)
        processed_today += 1
        
        print(f"    ✅ Success (Title: {row['title_chinese']})")
        time.sleep(DELAY_BETWEEN_JOBS)

    print(f"\n{'='*80}")
    print(f"Phase 2 Completed")
    print(f"Processed: {processed_today}, Skipped: {skipped}, Failed: {failed}")
    print(f"{'='*80}\n")


def generate_additional_fields():
    print(f"\n{'='*80}")
    print(f"Starting: Generate additional fields")
    print(f"{'='*80}\n")

    if not os.path.exists(OUTPUT_FILE):
        print(f"❌ File not found: {OUTPUT_FILE}")
        return

    updated_count = 0
    all_rows = []
    
    with open(OUTPUT_FILE, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # source_name_english
            if not row.get('source_name_english') or row.get('source_name_english') == 'wellfound':
                row['source_name'] = 'Wellfound'
                row['source_name_english'] = 'Wellfound'
            
            # salary_english
            # If current salary_english and salary are same, it might need cleanup or already processed
            # But the primary generator is now in content.js. 
            # We just ensure source names are correct here.
            if row.get('source_name') == 'wellfound':
                row['source_name'] = 'Wellfound'
            if row.get('source_name_english') == 'wellfound':
                row['source_name_english'] = 'Wellfound'
            
            # type
            if not row.get('type'):
                row['type'] = classify_job_type(
                    row.get('title', ''),
                    row.get('description', ''),
                    row.get('team', '')
                )
            
            all_rows.append(row)
            updated_count += 1
    
    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)
        
    print(f"✅ Updated {updated_count} rows with new fields.")
    
    # Finally copy to jobs_final.csv
    # This ensures jobs_final is always the latest processed version
    import shutil
    shutil.copy(OUTPUT_FILE, FINAL_OUTPUT_FILE)
    print(f"✅ Copied to {FINAL_OUTPUT_FILE}")
