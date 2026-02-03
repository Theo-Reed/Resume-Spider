"""
CSV handling utilities for job data
"""

import csv
import os
import hashlib


def generate_job_id(source_url: str) -> str:
    if not source_url:
        return ""
    return hashlib.md5(source_url.encode()).hexdigest()


fieldnames = [
    "_id", "title", "title_chinese", "title_english", "team", "summary", "summary_chinese", "summary_english", "salary", "salary_english",
    "createdAt", "source_name", "source_name_english", "source_url", "type", "description", "description_chinese", "description_english",
    "city", "experience", "is_remote"
]


def save_to_csv(filename, jobs, _type="国内"):
    def headers_are_correct(file_path, expected_headers):
        with open(file_path, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            return next(reader, None) == expected_headers

    def load_existing_keys(file_path):
        keys = set()
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8-sig") as f:
                for _row in csv.DictReader(f):
                    keys.add(_row.get("_id"))
        return keys

    if os.path.exists(filename) and not headers_are_correct(filename, fieldnames):
        os.remove(filename)

    existing_keys = load_existing_keys(filename)
    write_header = not os.path.exists(filename)

    written = 0
    skipped_dupe = 0

    with open(filename, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        for item in jobs:
            job_id = generate_job_id(item.get("source_url"))
            if job_id in existing_keys:
                skipped_dupe += 1
                continue
            row = {k: v for k, v in item.items() if k != "link"}
            row["_id"] = job_id
            row["type"] = item.get("type", _type)
            writer.writerow(row)
            existing_keys.add(job_id)
            written += 1

    print(f"✅ save_to_csv -> written: {written}, skipped duplicates: {skipped_dupe}, file: {filename}")


def aggregate_csv_by_type(
    source_dir: str = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "websites", "csv-website-file")),
    target_dir: str = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "websites", "csv-type-file")),
    domestic_output: str = 'domestic_remote_jobs.csv',
    abroad_output: str = 'abroad_remote_jobs.csv',
    web3_output: str = 'web3_remote_jobs.csv'):
    if not os.path.isdir(source_dir):
        return

    os.makedirs(target_dir, exist_ok=True)

    output_files = {
        '国内': os.path.join(target_dir, domestic_output),
        '国外': os.path.join(target_dir, abroad_output),
        'web3': os.path.join(target_dir, web3_output),
    }
    output_names = {os.path.basename(p) for p in output_files.values()}

    csv_files = [
        os.path.join(source_dir, name)
        for name in os.listdir(source_dir)
        if name.lower().endswith('.csv') and name not in output_names
    ]

    jobs_by_type = {"国内": [], "国外": [], "web3": []}
    seen_ids = set()

    def normalize_type(t: str) -> str:
        if not t:
            return '国内'
        t_low = t.lower()
        if 'web3' in t_low:
            return 'web3'
        if '外' in t or 'abroad' in t_low or 'oversea' in t_low:
            return '国外'
        return '国内'

    for file_path in csv_files:
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    job_id = row.get('_id') or ''
                    if not job_id or job_id in seen_ids:
                        continue
                    job_type = normalize_type(row.get('type', '国内'))
                    row['type'] = job_type
                    jobs_by_type[job_type].append(row)
                    seen_ids.add(job_id)
        except Exception:
            pass

    for job_type, out_path in output_files.items():
        jobs = jobs_by_type[job_type]
        jobs.sort(key=lambda x: x.get('createdAt', ''), reverse=True)
        # do not delete existing file; let save_to_csv handle duplicate detection
        save_to_csv(out_path, jobs, _type=job_type)


if __name__ == "__main__":
    aggregate_csv_by_type()
