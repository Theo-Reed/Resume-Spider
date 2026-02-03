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

_ZHILIAN_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE = os.path.join(_ZHILIAN_DIR, "csv_file", "jobs_meta_updated.csv")
OUTPUT_FILE = os.path.join(_ZHILIAN_DIR, "csv_file", "jobs_gemini_edited.csv")
FINAL_OUTPUT_FILE = os.path.join(_ZHILIAN_DIR, "csv_file", "jobs_final.csv")
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
    print(f"智联招聘 FUNCTION: Remove duplicate and invalid jobs")
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
    seen_descriptions = set()
    cleaned_jobs = []
    duplicates_removed = 0
    invalid_removed = 0
    
    for job in jobs:
        title = job.get('title', '').strip()
        team = job.get('team', '').strip()
        description = job.get('description', '').strip()
        
        # 归一化经验字段，不再丢弃岗位
        job['experience'] = is_valid_experience(job.get('experience', ''))
        
        title_team_key = (title, team)
        is_duplicate = False
        
        if title and team and title_team_key in seen_title_team:
            is_duplicate = True
        
        if description and description in seen_descriptions:
            is_duplicate = True
        
        if not is_duplicate:
            if title and team:
                seen_title_team.add(title_team_key)
            if description:
                seen_descriptions.add(description)
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
    print(f"\n{'='*80}")
    print(f"智联招聘 Phase 1: Merging and Sorting")
    print(f"{'='*80}\n")

    existing_jobs = {}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    jid = row.get('_id')
                    if jid:
                        for field in fieldnames:
                            if field not in row: row[field] = ''
                        existing_jobs[jid] = row
            print(f"📋 Loaded {len(existing_jobs)} existing jobs from {os.path.basename(OUTPUT_FILE)}")
        except Exception as e:
            print(f"⚠️ Error loading existing output file: {e}")

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
                    
                    if jid not in existing_jobs:
                        if not row.get('description'): continue
                        
                        # 在合并新数据时也进行归一化
                        row['experience'] = is_valid_experience(row.get('experience', ''))
                        
                        for field in fieldnames:
                            if field not in row: row[field] = ''
                        
                        existing_jobs[jid] = row
                        new_added_count += 1
            print(f"📥 Added {new_added_count} new jobs from {os.path.basename(INPUT_FILE)}")
        except Exception as e:
            print(f"⚠️ Error loading updated meta file: {e}")
    else:
        print(f"❌ Input file not found: {INPUT_FILE}")

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
    print(f"智联招聘 Phase 2: Processing with Gemini")
    print(f"{'='*80}\n")

    processed_ids, today_count, _ = _load_processed_status()
    if today_count >= DAILY_LIMIT:
        print(f"⚠️ Daily limit ({DAILY_LIMIT}) reached. Exiting.")
        return

    processed_today = 0
    skipped = 0
    today = datetime.now()

    for i, row in enumerate(all_jobs_list, 1):
        if processed_today >= DAILY_LIMIT:
            break
        
        job_id = row.get('_id', '')
        if row.get('is_remote') == '0':
            skipped += 1
            continue
            
        if row.get('title_chinese') and row.get('description_chinese'):
            skipped += 1
            continue
            
        description = row.get('description', '')
        is_valid, _ = is_valid_job_description(description)
        if not is_valid:
            skipped += 1
            continue

        print(f"[{i}/{len(all_jobs_list)}] Processing: {row.get('title', 'N/A')[:50]}")
        result = get_optimized_job_info(row.get('title', ''), row.get('description', ''))
        
        if not result:
            row['is_remote'] = '0'
            _update_output_file(job_id, row, fieldnames)
            processed_today += 1
            continue

        row['title_chinese'] = result.get('title_chinese', '')
        row['title_english'] = result.get('title_english', '')
        row['summary_chinese'] = ",".join(result.get('tags_chinese', []))
        row['summary_english'] = ",".join(result.get('tags_english', []))
        row['description_chinese'] = result.get('description_chinese', '')
        row['description_english'] = result.get('description_english', '')
        row['is_remote'] = '1'
        
        _update_output_file(job_id, row, fieldnames)
        processed_today += 1

        if processed_today < DAILY_LIMIT:
            time.sleep(DELAY_BETWEEN_JOBS)

    print(f"\n✅ All done: {processed_today} processed today, {skipped} skipped")


def generate_additional_fields():
    if not os.path.exists(OUTPUT_FILE):
        print(f"❌ Input file not found: {OUTPUT_FILE}")
        return

    print(f"\n{'='*80}")
    print(f"智联招聘 FUNCTION: Generate salary_english, type, and source_name_english")
    print(f"{'='*80}\n")

    jobs = []
    with open(OUTPUT_FILE, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            for field in fieldnames:
                if field not in row:
                    row[field] = ''
            jobs.append(row)
    
    updated_count = 0
    for job in jobs:
        updated = False
        
        salary_raw = job.get('salary', '').strip()
        if salary_raw:
            # 修正 salary 和 salary_english
            salary_fixed_cn = convert_salary_to_english(salary_raw, to_english=False)
            salary_fixed_en = convert_salary_to_english(salary_raw, to_english=True)
            
            # 更新原始 salary 字段为更简洁的格式
            if 'k' in salary_fixed_cn.lower():
                job['salary'] = salary_fixed_cn
                updated = True
            
            if job.get('salary_english', '').strip() != salary_fixed_en:
                job['salary_english'] = salary_fixed_en
                updated = True
        
        description = job.get('description', '').strip()
        description_chinese = job.get('description_chinese', '').strip()
        desc_text = description_chinese if not description else description
        if desc_text:
            job_type = classify_job_type(desc_text, "国内")
            if job.get('type', '').strip() != job_type:
                job['type'] = job_type
                updated = True
        
        source_name = job.get('source_name', '').strip()
        if source_name == '智联招聘':
            if job.get('source_name_english', '').strip() != 'Zhilian Zhaopin':
                job['source_name_english'] = 'Zhilian Zhaopin'
                updated = True
        
        if updated:
            updated_count += 1
    
    with open(FINAL_OUTPUT_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(jobs)
    print(f"\n✅ Successfully saved {len(jobs)} jobs to {FINAL_OUTPUT_FILE}")
