import csv
import json
import os
import re
import time
from datetime import datetime, date
import google.generativeai as genai
from typing import List, Dict, Any, Optional, Tuple
from util.type import classify_job_type
import re

# Configuration
GEMINI_API_KEY = "AIzaSyC-iCb05HZXEdtniblgTKsUPTJPQFVIzxI"
# Get boss folder (same directory as this file)
_BOSS_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE = os.path.join(_BOSS_DIR, "csv_file", "jobs_meta_updated.csv")
OUTPUT_FILE = os.path.join(_BOSS_DIR, "csv_file", "jobs_gemini_edited.csv")
FINAL_OUTPUT_FILE = os.path.join(_BOSS_DIR, "csv_file", "jobs_final.csv")
DAILY_LIMIT = 1000
DELAY_BETWEEN_JOBS = 2  # seconds

# Configure Gemini
genai.configure(api_key=GEMINI_API_KEY)
# Model priority list (in order of preference)
MODEL_LIST = [
    'gemini-2.5-pro',
    'gemini-3-flash'
]

# Global variable to track current model index
_current_model_index = None

FORBIDDEN_TAG_SUBSTRINGS = (
    "远程", "remote", "wfh", "work from home", "home office", "居家办公", "在家办公",
    "全员远程", "远程办公",
)


def _strip_code_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```json"):
        return t[7:-3].strip()
    if t.startswith("```"):
        return t[3:-3].strip()
    return t


def extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """
    使用正则表达式从模型返回的字符串中提取最外层的 JSON 块。
    用于处理 Gemini 可能在 JSON 后面多说一句话的情况。
    """
    if not text:
        return None
    
    try:
        # 寻找被 { 和 } 包围的部分，使用 DOTALL 模式匹配多行内容
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            json_str = match.group()
            return json.loads(json_str)
        else:
            return None
    except json.JSONDecodeError:
        return None


def _has_forbidden_remote_tag(tags: Any) -> bool:
    if not isinstance(tags, list):
        return False
    for tag in tags:
        s = str(tag).strip().lower()
        if not s:
            continue
        for sub in FORBIDDEN_TAG_SUBSTRINGS:
            if sub.lower() in s:
                return True
    return False


def _tags_len_ok(tags: Any) -> bool:
    return isinstance(tags, list) and 5 <= len(tags) <= 7


def _get_current_model() -> Optional[str]:
    """
    Get the current working model, or return the first model if none is set.
    Returns the model name, or None if all models are exhausted.
    """
    global _current_model_index
    
    # If we already have a working model, return it
    if _current_model_index is not None and _current_model_index < len(MODEL_LIST):
        model_name = MODEL_LIST[_current_model_index]
        return model_name
    
    # First time, start with the first model
    if _current_model_index is None:
        _current_model_index = 0
    
    if _current_model_index >= len(MODEL_LIST):
        return None
    
    return MODEL_LIST[_current_model_index]


def _switch_to_next_model() -> Optional[str]:
    """
    Switch to the next model in the list when current model quota is exhausted.
    Returns the new model name if available, None if all exhausted.
    """
    global _current_model_index
    
    if _current_model_index is None:
        _current_model_index = 0
    else:
        _current_model_index += 1
    
    if _current_model_index >= len(MODEL_LIST):
        print(f"    ❌ All models exhausted, no more models to try")
        return None
    
    model_name = MODEL_LIST[_current_model_index]
    print(f"    🔄 Switching to next model: {model_name}")
    return model_name


def get_optimized_job_info(original_title: str, description: str) -> Dict:
    """
    Calls Gemini to generate Chinese and English translations for title, tags, and description.
    Returns title_chinese, title_english, tags_chinese, tags_english, description_chinese, description_english.
    """
    prompt = f"""
<task>
Given <original_title> and <description>, generate the Chinese versions first, then translate them to English.

IMPORTANT CHECK FIRST:
- Check if the title OR description mentions remote work keywords: 远程 / remote / WFH / work from home / 居家办公 / 在家办公 / 全员远程 / 远程办公 / 远程岗位 / 支持远程 / 可远程 / remote work / remote position / work remotely
- If NEITHER the title NOR the description mentions remote work, this job is NOT a remote position. Return an empty JSON object: {{}}
- If at least one of them mentions remote work, proceed with the normal workflow below.

Workflow (only if remote work is mentioned):
1. Generate title_chinese (core version) → then translate to title_english
2. Generate tags_chinese (core version) → then translate to tags_english (one-to-one correspondence)
3. Generate description_chinese (core version) → then translate to description_english (preserve format structure)

CRITICAL REQUIREMENT: You MUST return ONLY valid JSON format. No markdown, no code blocks, no explanations, no additional text before or after the JSON.
</task>

<input>
<original_title>{original_title}</original_title>
<description>
{description}
</description>
</input>

<rules>

<title>
Step 1: Generate title_chinese (CORE VERSION)
- Extract the core role name from original_title; be short, professional, accurate.
- Remove noise words:
  - remote/location words: 远程 / remote / WFH / work from home / 居家办公 / 在家办公 / 全员远程 / 远程办公
- hiring phrases: 招聘 / 诚招 / 急招 / 急聘 / 紧急需求 / 内推 / 速招 / HC / headcount
- location info: 城市 / 地点 / 国内 / 国外 / 出海
- experience/education: 3-5年 / 5年以上 / 大厂 / 211 / 985 / 本科 / 硕士
- salary/benefits: 20-40K / 15薪 / 期权 / 双休
- bracket parts like: "(大厂/211/remote/3-5年)" or "【...】" or "（remote）"
- company/team name
- Keep tech terms as-is (e.g., Java, React, C++, Python)
- Output in pure Chinese

Step 2: Generate title_english (TRANSLATION OF title_chinese)
- Translate title_chinese to clear, professional English
- Keep technical terms as-is (e.g., Java, React, C++, Python)
- Maintain the same meaning and tone as title_chinese
</title>

<tags>
Step 1: Generate tags_chinese (CORE VERSION)
- Extract 5-7 tags from the description following the order and rules below
- If an optional category (like industry) is unclear, DO NOT output it; instead, fill with other high-signal info so the total still stays 5-7

Tag order and meaning (very important):
1. Major Work (必填): A concise phrase (MAX 8 Chinese characters) describing the core work. This should COMPLEMENT title_chinese, NOT duplicate it.
   - Must be very brief and focused on the core work activity
   - MAX 8 Chinese characters (e.g., "产品从0到1规划", "游戏测试与自动化")
   - Should describe what the job actually does in a nutshell
   - Examples:
     * If title_chinese is "产品经理", first tag could be "产品从0到1规划" (then later tags like "B端SaaS产品" provide details)
     * If title_chinese is "测试工程师", first tag could be "游戏测试与自动化" (then later tags like "moba游戏" provide details)
     * If title_chinese is "前端开发工程师", first tag could be "React开发" or "前端组件开发"
     * If title_chinese is "运营专员", first tag could be "内容运营" or "用户增长运营"
   - AVOID tags that just repeat the title, e.g., if title is "Java开发工程师", don't use "Java开发" as the first tag
2. Industry (可选): only if it can be inferred as the MAIN industry/business from description, then include it.
   - Examples: "电商行业", "金融科技", "游戏行业", "区块链行业"
3-4. Key Work/Requirements (必填): most distinguishing tasks, technologies, or specific details that complement the first tag.
   - Can provide more detailed information, e.g., "B端SaaS产品", "moba游戏", "React+TypeScript", "从0到1实现App上架", "对接物流仓储", "熟悉KYC流程"
5. Company context (可选): 外企/美企/国内初创/国企等，仅在描述明确提到时输出。
6. Perks excluding salary (可选): 带薪年假/补充医疗/期权等，仅在描述明确提到时输出。
7. Other remote-seeker-important info (可选): e.g. "不加班", "弹性工作", "可异步", "跨时区协作"（仅在描述明确提到时输出）。

Length constraint:
- Max 20 units per tag.
- Unit rule: each Chinese character = 2 units; each English letter/digit/symbol = 1 unit.
- Keep tags concise; avoid long sentences.

Forbidden:
- remote/远程/WFH/全员远程办公 (dataset is all remote)
- salary numbers/compensation
- company/team names (unless category 5 and it's about type like 美企/外企; do not output actual company name)
- vague filler like "岗位职责", "优秀沟通", "有责任心"

Step 2: Generate tags_english (TRANSLATION OF tags_chinese)
- Translate each tag in tags_chinese to English, maintaining one-to-one correspondence (same order, same number of tags)
- Keep technical terms as-is (e.g., Java, React, C++, Python)
- Examples of translations:
  - "小红书运营" → "Xiaohongshu Operations"
  - "小程序前端开发" → "Mini Program Frontend Development"
  - "电商行业" → "E-commerce Industry"
  - "React+TypeScript" → "React+TypeScript" (keep as-is)
</tags>

<description>
Step 1: Generate description_chinese (CORE VERSION)
- Process the original description to create a clean Chinese version:
  1. If original is mostly Chinese with some English terms (Java/React/Amazon), keep those terms; only translate the English sentences to Chinese.
2. If bilingual (roughly 50/50), translate/merge into cohesive Chinese, preserving original punctuation/format/tone as much as possible.
  3. If original is mostly English, translate to Chinese.
- Preserve the original structure, formatting, line breaks, bullet points, numbering, etc.
- Keep technical terms as-is (e.g., Java, React, Python, AWS)
- Do not omit any details
- Ensure the output is professional, clear, and natural Chinese

Step 2: Generate description_english (TRANSLATION OF description_chinese)
- Translate description_chinese to English
- CRITICAL: Preserve the exact same structure and formatting as description_chinese:
  - Keep the same line breaks
  - Keep the same bullet points/numbering structure
  - Keep the same sections and paragraph breaks
  - Keep the same emphasis/formatting patterns
- Keep technical terms as-is (e.g., Java, React, Python, AWS)
- Maintain the same tone and meaning as description_chinese
- Do not omit any details
- The structure of description_english should mirror description_chinese exactly
</description>

<output_format>
CRITICAL: You MUST return ONLY valid JSON. No markdown, no code blocks, no explanations, no additional text.

If the job is NOT remote (no remote work keywords found), return an empty JSON object: {{}}

If the job IS remote, the output MUST be a valid JSON object with EXACT keys:
{{
  "title_chinese": "...",
  "title_english": "...",
  "tags_chinese": ["... (5-7 items) ..."],
  "tags_english": ["... (5-7 items) ..."],
  "description_chinese": "...",
  "description_english": "..."
}}

IMPORTANT:
- Return ONLY the JSON object itself
- Do NOT wrap it in ```json``` or ``` blocks
- Do NOT add any comments or explanations before or after the JSON
- The response must start with {{ and end with }}
- All strings must be properly escaped if they contain quotes

Example of correct output:
{{"title_chinese": "软件工程师", "title_english": "Software Engineer", "tags_chinese": ["后端开发", "Java", "Spring"], "tags_english": ["Backend Development", "Java", "Spring"], "description_chinese": "...", "description_english": "..."}}
</output_format>

</rules>
"""
    def _call_gemini(p: str, model_name: str) -> Optional[Dict[str, Any]]:
        last_error = None
        error_type = None
        last_content = None
        
        for attempt in range(6):
            try:
                current_model = genai.GenerativeModel(model_name)
                response = current_model.generate_content(p)
                content = _strip_code_fences(getattr(response, "text", "") or "")
                last_content = content
                
                if not content:
                    raise ValueError("Gemini returned empty response")
                
                # Try direct JSON parsing first
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    # If direct parsing fails, try to extract JSON from text
                    # (Gemini might have added extra text after JSON)
                    extracted = extract_json_from_text(content)
                    if extracted:
                        print(f"    ✅ Fixed JSON by extracting from text (model: {model_name})")
                        return extracted
                    # If extraction also fails, raise the error to continue retry logic
                    raise
            except json.JSONDecodeError as e:
                last_error = e
                error_type = "JSON_PARSE"
                # JSON parse error - might be Gemini format issue
                if attempt < 3:
                    print(f"    ⚠️  Attempt {attempt + 1}/6: JSON parse error (model: {model_name}), retrying...")
                    print(f"       Response preview: {last_content[:200] if last_content else 'empty'}")
                    time.sleep(2)
                    continue
            except Exception as e:
                last_error = e
                msg = str(e).lower()
                
                # API errors (Gemini side)
                if "429" in str(e) or "quota" in msg or "rate" in msg:
                    error_type = "API_QUOTA"
                    # If quota exhausted on first attempt, don't retry with same model
                    if attempt == 0:
                        print(f"    ⚠️  Quota exhausted for model: {model_name} (first attempt)")
                        # Raise special exception to trigger model switch
                        raise Exception("QUOTA_EXHAUSTED")
                    # For later attempts (rate limit, not quota exhaustion), wait and retry
                    sleep_s = min(60, 5 * (attempt + 1))
                    print(f"    ⚠️  Attempt {attempt + 1}/6: API rate limit (model: {model_name}), waiting {sleep_s}s...")
                    time.sleep(sleep_s)
                    continue
                elif "403" in str(e) or "permission" in msg or "forbidden" in msg:
                    error_type = "API_PERMISSION"
                    print(f"    ❌ API permission error (model: {model_name}): {e}")
                    return None
                elif "401" in str(e) or "unauthorized" in msg or "api_key" in msg:
                    error_type = "API_AUTH"
                    print(f"    ❌ API authentication error (model: {model_name}): {e}")
                    return None
                elif "404" in str(e) or "not found" in msg:
                    error_type = "API_MODEL_NOT_FOUND"
                    print(f"    ❌ Model not found (model: {model_name}): {e}")
                    return None
                elif "network" in msg or "connection" in msg or "timeout" in msg:
                    error_type = "API_NETWORK"
                    if attempt < 4:
                        sleep_s = min(30, 3 * (attempt + 1))
                        print(f"    ⚠️  Attempt {attempt + 1}/6: Network error (model: {model_name}), retrying in {sleep_s}s...")
                        time.sleep(sleep_s)
                        continue
                else:
                    error_type = "API_OTHER"
                    if attempt < 2:
                        print(f"    ⚠️  Attempt {attempt + 1}/6: API error (model: {model_name}), retrying...")
                        time.sleep(1)
                        continue
        
        # All retries exhausted - report detailed error
        if last_error:
            error_msg = str(last_error)
            if error_type == "JSON_PARSE":
                print(f"    ❌ CODE ISSUE: JSON parsing failed after 6 attempts (model: {model_name})")
                print(f"       Error: {error_msg}")
                print(f"       This suggests Gemini returned invalid JSON format")
                print(f"       Last response preview: {last_content[:300] if last_content else 'N/A'}")
            elif error_type == "API_QUOTA":
                print(f"    ❌ GEMINI API ISSUE: Quota/rate limit exceeded after 6 attempts (model: {model_name})")
                print(f"       Error: {error_msg}")
                print(f"       Please check your Gemini API quota/plan")
            elif error_type == "API_NETWORK":
                print(f"    ❌ GEMINI API ISSUE: Network/connection problem after 6 attempts (model: {model_name})")
                print(f"       Error: {error_msg}")
            elif error_type == "API_MODEL_NOT_FOUND":
                print(f"    ❌ GEMINI API ISSUE: Model not found (model: {model_name})")
                print(f"       Error: {error_msg}")
            else:
                print(f"    ❌ GEMINI API ISSUE: {error_type or 'Unknown error'} after 6 attempts (model: {model_name})")
                print(f"       Error: {error_msg}")
        else:
            print(f"    ❌ Unknown error: exceeded retries without error details (model: {model_name})")
        
        return None

    # Get current model (or start with first model)
    current_model = _get_current_model()
    if not current_model:
        print(f"    ❌ No available models, all exhausted")
        return None
    
    if _current_model_index == 0:
        print(f"    🤖 Starting with model: {current_model}")
    
    # Try calling with current model, with automatic model switching on quota exhaustion
    result = None
    max_model_switches = len(MODEL_LIST)
    switch_count = 0
    
    while switch_count < max_model_switches and current_model:
        try:
            result = _call_gemini(prompt, current_model)
            if result:
                # Success! This model works, keep using it
                print(f"    ✅ Success with model: {current_model}")
                break
        except Exception as e:
            if "QUOTA_EXHAUSTED" in str(e):
                # Quota exhausted, switch to next model
                current_model = _switch_to_next_model()
                if current_model:
                    switch_count += 1
                    print(f"    🔄 Quota exhausted, switched to model: {current_model} (switch {switch_count}/{max_model_switches})")
                    continue
                else:
                    print(f"    ❌ All models exhausted")
                    return None
            else:
                # Other errors, break and return None
                print(f"    ❌ Unexpected error: {e}")
                break
    
    if not result:
        return None

    # If Gemini violates hard constraints (remote tags or tag count), retry once with a correction.
    tags_chinese = result.get("tags_chinese")
    tags_english = result.get("tags_english")
    if _has_forbidden_remote_tag(tags_chinese) or _has_forbidden_remote_tag(tags_english) or (not _tags_len_ok(tags_chinese)) or (not _tags_len_ok(tags_english)):
        correction = """
<correction>
Your previous output violated constraints.
- DO NOT include any remote/远程/WFH related tags (all jobs are remote).
- "tags_chinese" and "tags_english" MUST each contain 5-7 items.
Re-generate the JSON with the SAME required keys and rules.
CRITICAL: Return ONLY valid JSON. No markdown, no code blocks, no explanations.
</correction>
"""
        print(f"    🔧 Constraint violation detected, retrying with correction (model: {current_model})...")
        result2 = _call_gemini(correction + "\n" + prompt, current_model)
        return result2 or result

    return result


def translate_chinese_to_english(jobs_batch: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Translate title_chinese, description_chinese, summary_chinese to English for a batch of jobs.
    Returns a list of dictionaries with translations added.
    """
    def _call_gemini_translate(p: str, model_name: str) -> Optional[Dict[str, Any]]:
        last_error = None
        error_type = None
        last_content = None
        
        for attempt in range(6):
            try:
                current_model = genai.GenerativeModel(model_name)
                response = current_model.generate_content(p)
                content = _strip_code_fences(getattr(response, "text", "") or "")
                last_content = content
                
                if not content:
                    raise ValueError("Gemini returned empty response")
                
                # Try direct JSON parsing first
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    # If direct parsing fails, try to extract JSON from text
                    extracted = extract_json_from_text(content)
                    if extracted:
                        print(f"    ✅ Fixed JSON by extracting from text (model: {model_name})")
                        return extracted
                    raise
            except json.JSONDecodeError as e:
                last_error = e
                error_type = "JSON_PARSE"
                if attempt < 3:
                    print(f"    ⚠️  Attempt {attempt + 1}/6: JSON parse error (model: {model_name}), retrying...")
                    print(f"       Response preview: {last_content[:200] if last_content else 'empty'}")
                    time.sleep(2)
                    continue
            except Exception as e:
                last_error = e
                msg = str(e).lower()
                
                if "429" in str(e) or "quota" in msg or "rate" in msg:
                    error_type = "API_QUOTA"
                    if attempt == 0:
                        print(f"    ⚠️  Quota exhausted for model: {model_name} (first attempt)")
                        raise Exception("QUOTA_EXHAUSTED")
                    sleep_s = min(60, 5 * (attempt + 1))
                    print(f"    ⚠️  Attempt {attempt + 1}/6: API rate limit (model: {model_name}), waiting {sleep_s}s...")
                    time.sleep(sleep_s)
                    continue
                elif "403" in str(e) or "permission" in msg or "forbidden" in msg:
                    error_type = "API_PERMISSION"
                    print(f"    ❌ API permission error (model: {model_name}): {e}")
                    return None
                elif "401" in str(e) or "unauthorized" in msg or "api_key" in msg:
                    error_type = "API_AUTH"
                    print(f"    ❌ API authentication error (model: {model_name}): {e}")
                    return None
                elif "404" in str(e) or "not found" in msg:
                    error_type = "API_MODEL_NOT_FOUND"
                    print(f"    ❌ Model not found (model: {model_name}): {e}")
                    return None
                elif "network" in msg or "connection" in msg or "timeout" in msg:
                    error_type = "API_NETWORK"
                    if attempt < 4:
                        sleep_s = min(30, 3 * (attempt + 1))
                        print(f"    ⚠️  Attempt {attempt + 1}/6: Network error (model: {model_name}), retrying in {sleep_s}s...")
                        time.sleep(sleep_s)
                        continue
                else:
                    error_type = "API_OTHER"
                    if attempt < 2:
                        print(f"    ⚠️  Attempt {attempt + 1}/6: API error (model: {model_name}), retrying...")
                        time.sleep(1)
                        continue
        
        if last_error:
            error_msg = str(last_error)
            if error_type == "JSON_PARSE":
                print(f"    ❌ JSON parsing failed after 6 attempts (model: {model_name})")
                print(f"       Error: {error_msg}")
                print(f"       Last response preview: {last_content[:300] if last_content else 'N/A'}")
            else:
                print(f"    ❌ Translation API error: {error_type or 'Unknown error'} after 6 attempts (model: {model_name})")
                print(f"       Error: {error_msg}")
        else:
            print(f"    ❌ Unknown error: exceeded retries without error details (model: {model_name})")
        
        return None

    # Build prompt with all jobs in batch
    jobs_data = []
    for idx, job in enumerate(jobs_batch):
        job_id = job.get('_id', '')
        title_chinese = job.get('title_chinese', '').strip()
        description_chinese = job.get('description_chinese', '').strip()
        summary_chinese = job.get('summary_chinese', '').strip()
        
        jobs_data.append({
            'id': job_id,
            'title_chinese': title_chinese,
            'description_chinese': description_chinese,
            'summary_chinese': summary_chinese
        })
    
    prompt = f"""
<task>
Translate the Chinese fields to English for {len(jobs_data)} jobs.
For each job, translate:
1) title_chinese -> title_english
2) description_chinese -> description_english  
3) summary_chinese -> summary_english (this is a comma-separated list of tags, translate each tag and keep comma-separated format)

CRITICAL REQUIREMENT: You MUST return ONLY valid JSON format. No markdown, no code blocks, no explanations, no additional text before or after the JSON.
</task>

<jobs>
{json.dumps(jobs_data, ensure_ascii=False, indent=2)}
</jobs>

<rules>
- title_english: Translate the job title to clear, professional English. Keep technical terms as-is (e.g., Java, React, Python).
- description_english: Translate the full job description to English. Preserve formatting, structure, and technical terms.
- summary_english: Translate each tag in the comma-separated summary_chinese to English, keeping the comma-separated format. Keep technical terms as-is.

If a field is empty or missing, return an empty string for that field.
Preserve the meaning and tone of the original text.
</rules>

<output_format>
CRITICAL: You MUST return ONLY valid JSON. No markdown, no code blocks, no explanations.

The output MUST be a valid JSON object with this structure:
{{
  "translations": [
    {{
      "id": "job_id_1",
      "title_english": "...",
      "description_english": "...",
      "summary_english": "..."
    }},
    {{
      "id": "job_id_2",
      "title_english": "...",
      "description_english": "...",
      "summary_english": "..."
    }}
  ]
}}

IMPORTANT:
- Return ONLY the JSON object itself
- Do NOT wrap it in ```json``` or ``` blocks
- Do NOT add any comments or explanations
- The response must start with {{ and end with }}
- All strings must be properly escaped if they contain quotes
- Include translations for ALL {len(jobs_data)} jobs in the same order as input
</output_format>
"""
    
    # Get current model
    current_model = _get_current_model()
    if not current_model:
        print(f"    ❌ ERROR: No available models for translation, all models exhausted")
        return None  # Return None to indicate failure
    
    if _current_model_index == 0:
        print(f"    🤖 Starting translation with model: {current_model}")
    
    # Try calling with current model
    result = None
    max_model_switches = len(MODEL_LIST)
    switch_count = 0
    
    while switch_count < max_model_switches and current_model:
        try:
            result = _call_gemini_translate(prompt, current_model)
            if result:
                # Verify result has expected structure
                if 'translations' in result and isinstance(result['translations'], list):
                    print(f"    ✅ SUCCESS: Translation completed with model: {current_model}")
                    print(f"       Received {len(result['translations'])} translation(s)")
                    break
                else:
                    print(f"    ⚠️  WARNING: Translation response missing 'translations' field")
                    result = None
        except Exception as e:
            if "QUOTA_EXHAUSTED" in str(e):
                # Quota exhausted, switch to next model
                current_model = _switch_to_next_model()
                if current_model:
                    switch_count += 1
                    print(f"    🔄 Quota exhausted on previous model, switching to: {current_model} (switch {switch_count}/{max_model_switches})")
                    continue
                else:
                    print(f"    ❌ ERROR: All models exhausted, cannot continue translation")
                    return None
            else:
                print(f"    ❌ ERROR: Unexpected translation error: {e}")
                break
    
    if not result:
        print(f"    ❌ FAILED: Translation API call failed after trying {switch_count + 1} model(s)")
        return None  # Return None to indicate failure
    
    # Map translations back to jobs
    translations_dict = {}
    translations_list = result.get('translations', [])
    found_count = 0
    for trans in translations_list:
        job_id = trans.get('id', '')
        if job_id:
            translations_dict[job_id] = {
                'title_english': trans.get('title_english', ''),
                'description_english': trans.get('description_english', ''),
                'summary_english': trans.get('summary_english', '')
            }
            found_count += 1
    
    if found_count != len(jobs_batch):
        print(f"    ⚠️  WARNING: Expected {len(jobs_batch)} translations, received {found_count}")
    
    # Update jobs with translations
    updated_jobs = []
    missing_count = 0
    for job in jobs_batch:
        job_id = job.get('_id', '')
        if job_id in translations_dict:
            job['title_english'] = translations_dict[job_id]['title_english']
            job['description_english'] = translations_dict[job_id]['description_english']
            job['summary_english'] = translations_dict[job_id]['summary_english']
        else:
            # If translation not found, set empty strings
            missing_count += 1
            job['title_english'] = ''
            job['description_english'] = ''
            job['summary_english'] = ''
        updated_jobs.append(job)
    
    if missing_count > 0:
        print(f"    ⚠️  WARNING: {missing_count} job(s) missing translations in response")
    
    return updated_jobs


def _is_valid_job_description(description: str) -> Tuple[bool, str]:
    """
    Check if job description is valid (has enough content).
    
    Args:
        description: Job description text (can be mixed Chinese/English)
    
    Returns:
        Tuple of (is_valid, reason_message)
        - is_valid: True if description is valid (>= 20 Chinese chars OR >= 30 English chars, excluding punctuation)
        - reason_message: Explanation of why it's invalid (empty if valid)
    """
    if not description:
        return False, "Description is empty"
    
    # Remove all punctuation (Chinese and English)
    # Chinese punctuation: ，。！？；：""''（）【】《》…—、等
    chinese_punct = '，。！？；：""''（）【】《》…—、·【】「」『』〈〉《》'
    # English punctuation
    english_punct = '!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~'
    all_punct = chinese_punct + english_punct
    
    # Remove punctuation
    text_no_punct = description.translate(str.maketrans('', '', all_punct))
    
    # Separate Chinese characters and English characters
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', text_no_punct)  # Chinese Unicode range
    english_chars = re.findall(r'[a-zA-Z0-9]', text_no_punct)  # English alphanumeric
    
    chinese_count = len(chinese_chars)
    english_count = len(english_chars)
    
    # Check validity: need at least 20 Chinese chars OR at least 30 English chars
    if chinese_count < 20 and english_count < 30:
        reason = f"Description too short: {chinese_count} Chinese chars, {english_count} English chars (need >= 20 Chinese OR >= 30 English)"
        return False, reason
    
    return True, ""


def _load_processed_status() -> Tuple[set, int, Optional[str]]:
    """
    Load processed job status from output file.
    Returns:
    - processed_ids: set of job IDs that have title_chinese filled (completed)
    - today_count: count of completed jobs
    - start_from_id: first job ID with empty title_chinese (where to resume), or None
    """
    processed_ids = set()
    today_count = 0
    start_from_id = None
    
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                job_id = row.get('_id', '')
                title_chinese = row.get('title_chinese', '').strip()
                
                if job_id:
                    if title_chinese:
                        # This job is completed
                        processed_ids.add(job_id)
                        today_count += 1
                    elif start_from_id is None:
                        # This is the first incomplete job, start from here
                        start_from_id = job_id
    
    return processed_ids, today_count, start_from_id


def _load_translation_status() -> Tuple[set, int, Optional[str]]:
    """
    Load translation status from output file.
    Returns:
    - processed_ids: set of job IDs that have title_english filled (completed translations)
    - today_count: count of completed jobs with translations
    - start_from_id: first job ID with empty title_english (where to resume), or None
    """
    processed_ids = set()
    today_count = 0
    start_from_id = None
    
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                job_id = row.get('_id', '')
                title_english = row.get('title_english', '').strip()
                
                if job_id:
                    if title_english:
                        # This job is completed (has English translation)
                        processed_ids.add(job_id)
                        today_count += 1
                    elif start_from_id is None:
                        # This is the first incomplete job, start from here
                        start_from_id = job_id
    
    return processed_ids, today_count, start_from_id


def _load_output_file() -> Tuple[Dict[str, Dict], List[Dict]]:
    """
    Load output file and return:
    - job_id_to_row: mapping of job_id to row data
    - all_rows: list of all rows in order
    """
    from util.handle_csv import fieldnames
    
    job_id_to_row = {}
    all_rows = []
    
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Ensure all fieldnames are present (initialize missing fields with empty strings)
                for field in fieldnames:
                    if field not in row:
                        row[field] = ''
                
                job_id = row.get('_id', '')
                if job_id:
                    job_id_to_row[job_id] = row
                all_rows.append(row)
    
    return job_id_to_row, all_rows


def _update_output_file(job_id: str, updated_row: Dict, fieldnames: List[str]):
    """
    Update a specific row in the output file, or append if not exists.
    """
    job_id_to_row, all_rows = _load_output_file()
    
    # Update or add the row
    if job_id in job_id_to_row:
        # Update existing row
        for i, row in enumerate(all_rows):
            if row.get('_id') == job_id:
                all_rows[i] = updated_row
                break
    else:
        # Append new row
        all_rows.append(updated_row)
    
    # Write back to file
    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)


def _update_output_file_batch(updated_rows: List[Dict], fieldnames: List[str]):
    """
    Update multiple rows in the output file in batch.
    """
    job_id_to_row, all_rows = _load_output_file()
    
    # Create a mapping of job_id to updated_row
    updated_dict = {row.get('_id', ''): row for row in updated_rows if row.get('_id')}
    
    # Update existing rows or append new ones
    for i, row in enumerate(all_rows):
        job_id = row.get('_id', '')
        if job_id in updated_dict:
            all_rows[i] = updated_dict[job_id]
            del updated_dict[job_id]  # Remove from dict after updating
    
    # Append any new rows that weren't in the file
    for job_id, updated_row in updated_dict.items():
        all_rows.append(updated_row)
    
    # Write back to file
    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)


# ============================================================================
# FUNCTION 5: Generate salary_english, type, and source_name_english
# ============================================================================
def convert_salary_to_english(salary: str) -> str:
    """
    Convert salary from Chinese format to English format.
    - If contains '元/天', replace with '/day' (e.g., '12元/天' -> '12/day')
    - If contains '元/月', replace with '/mo' (e.g., '2000元/月' -> '2000/mo')
    - If contains '元/周', replace with '/wk' (e.g., '2000元/周' -> '2000/wk')
    - If contains 'xx薪' like '14薪', replace with 'xx pays/yr'
    - Example: '14-15k' -> '14-15k' (no change)
    - Example: '14薪' -> '14 pays/yr'
    - Example: '18-35K·14薪' -> '18-35K·14 pays/yr'
    """
    if not salary:
        return ''
    
    salary_english = salary
    
    # Replace '元/天' with '/day' (remove 元 before replacing)
    salary_english = re.sub(r'元/天', '/day', salary_english)
    
    # Replace '元/月' with '/mo'
    salary_english = re.sub(r'元/月', '/mo', salary_english)
    
    # Replace '元/周' with '/wk'
    salary_english = re.sub(r'元/周', '/wk', salary_english)
    
    # Replace '薪' with ' pays/yr'
    # Use regex to replace any number followed by '薪' with 'number pays/yr'
    salary_english = re.sub(r'(\d+)薪', r'\1 pays/yr', salary_english)
    
    return salary_english.strip()


def generate_additional_fields():
    """
    FUNCTION 5: Generate salary_english, type, and source_name_english for jobs
    
    Workflow:
    1. Read jobs from jobs_gemini_edited.csv
    2. Filter jobs: skip jobs without title_english or description_english
    3. For each job:
       - Generate salary_english from salary field
       - Generate type from description (check web3 keywords)
       - Generate source_name_english from source_name (if BOSS直聘 -> BOSS Zhipin)
    4. Save updated jobs to jobs_final.csv (new file, does not modify jobs_gemini_edited.csv)
    """
    if not os.path.exists(OUTPUT_FILE):
        print(f"❌ Input file not found: {OUTPUT_FILE}")
        return

    from util.handle_csv import fieldnames

    print(f"\n{'='*80}")
    print(f"FUNCTION 5: Generate salary_english, type, and source_name_english")
    print(f"{'='*80}\n")

    # 1. Read all jobs from input file and filter
    jobs = []
    skipped_count = 0
    with open(OUTPUT_FILE, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Ensure all fields exist
            for field in fieldnames:
                if field not in row:
                    row[field] = ''
            
            # Skip jobs without title_english or description_english
            title_english = row.get('title_english', '').strip()
            description_english = row.get('description_english', '').strip()
            if not title_english or not description_english:
                skipped_count += 1
                continue

            jobs.append(row)
    
    print(f"   Total jobs read: {len(jobs) + skipped_count}")
    print(f"   Jobs with title_english and description_english: {len(jobs)}")
    if skipped_count > 0:
        print(f"   Skipped jobs (missing title_english or description_english): {skipped_count}")
    
    # 2. Update each job
    updated_count = 0
    for job in jobs:
        updated = False
        
        # 2.1. Generate salary_english from salary
        salary = job.get('salary', '').strip()
        if salary:
            salary_english = convert_salary_to_english(salary)
            if job.get('salary_english', '').strip() != salary_english:
                job['salary_english'] = salary_english
                updated = True
        
        # 2.2. Generate type from description
        description = job.get('description', '').strip()
        description_chinese = job.get('description_chinese', '').strip()
        desc_text = description_chinese if not description else description
        if desc_text:
            job_type = classify_job_type(desc_text, "国内")
            if job.get('type', '').strip() != job_type:
                job['type'] = job_type
                updated = True
        elif not job.get('type', '').strip():
            job['type'] = '国内'
            updated = True
        
        # 2.3. Generate source_name_english from source_name
        source_name = job.get('source_name', '').strip()
        if source_name == 'BOSS直聘':
            if job.get('source_name_english', '').strip() != 'BOSS Zhipin':
                job['source_name_english'] = 'BOSS Zhipin'
                updated = True
        
        if updated:
            updated_count += 1
    
    print(f"\n   Updated {updated_count} jobs")
    
    # 3. Save jobs to new output file (does not modify jobs_gemini_edited.csv)
    with open(FINAL_OUTPUT_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(jobs)
    print(f"\n✅ Successfully saved {len(jobs)} jobs to {FINAL_OUTPUT_FILE}")


# ============================================================================
# FUNCTION 4: Remove duplicate jobs with same title and team, or same description
# ============================================================================
def _is_valid_experience(experience: str) -> bool:
    """
    Check if experience field is valid.
    Valid formats ONLY:
    - '经验不限'
    - '1年以内' (only this specific format)
    - '数字-数字年' (e.g., '1-3年', '3-5年', '1-10年')
    - '数字年以上' (e.g., '10年以上', '5年以上')
    
    Invalid formats (will be rejected):
    - Empty string
    - '在校生', '在校/应届'
    - Any other format
    
    Args:
        experience: Experience field value
    
    Returns:
        True if valid, False otherwise
    """
    if not experience:
        return False
    
    experience = experience.strip()
    
    # Check for '经验不限'
    if experience == '经验不限':
        return True
    
    # Check for '数字-数字年' format (e.g., '1-3年', '3-5年', '1-10年')
    # Pattern: one or more digits, hyphen, one or more digits, followed by '年'
    pattern1 = r'^\d+-\d+年$'
    if re.match(pattern1, experience):
        return True
    
    # Check for '1年以内' (only this specific format, not other numbers)
    if experience == '1年以内':
        return True
    
    # Check for '数字年以上' format (e.g., '10年以上')
    pattern3 = r'^\d+年以上$'
    if re.match(pattern3, experience):
        return True
    
    return False


def remove_duplicate_jobs(option = 2):
    if option == 1:
        csv_file = INPUT_FILE
    else:
        csv_file = OUTPUT_FILE
    """
    FUNCTION 3: Remove duplicate jobs and invalid jobs
    
    Removes:
    - Duplicate jobs: Same title AND same team, OR same description
    - Invalid jobs: experience field is not in valid format ('经验不限' or '数字-数字年')
    
    Workflow:
    1. Read jobs from output_file (jobs_gemini_edited.csv)
    2. Track seen (title, team) combinations and seen descriptions
    3. Check experience field validity
    4. Keep only valid, non-duplicate jobs
    5. Save the cleaned jobs back to output_file
    """
    if not os.path.exists(csv_file):
        print(f"❌ Output file not found: {csv_file}")
        return

    from util.handle_csv import fieldnames

    print(f"\n{'='*80}")
    print(f"FUNCTION 3: Remove duplicate and invalid jobs")
    print(f"{'='*80}\n")

    # 1. Read all jobs from output file
    jobs = []
    with open(csv_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Ensure all fields exist
            for field in fieldnames:
                if field not in row:
                    row[field] = ''
            jobs.append(row)
    
    print(f"   Total jobs before cleaning: {len(jobs)}")

    # 2. Track seen (title, team) combinations and seen descriptions
    seen_title_team = set()
    seen_descriptions = set()
    cleaned_jobs = []
    duplicates_removed = 0
    invalid_removed = 0
    
    for job in jobs:
        title = job.get('title', '').strip()
        team = job.get('team', '').strip()
        description = job.get('description', '').strip()
        experience = job.get('experience', '').strip()
        
        # Check if experience is valid
        if not _is_valid_experience(experience):
            invalid_removed += 1
            continue
        
        # Create key for duplicate detection
        title_team_key = (title, team)
        
        # Check if this job is a duplicate
        is_duplicate = False
        
        # Check if (title, team) combination was seen before (only if both are non-empty)
        if title and team and title_team_key in seen_title_team:
            is_duplicate = True
        
        # Check if description was seen before (only if description is not empty)
        if description and description in seen_descriptions:
            is_duplicate = True
        
        if not is_duplicate:
            # First time seeing this combination/description, keep this job
            # Track (title, team) combination (only if both are non-empty)
            if title and team:
                seen_title_team.add(title_team_key)
            # Track description (only if non-empty)
            if description:
                seen_descriptions.add(description)
            cleaned_jobs.append(job)
        else:
            # Duplicate found, skip this job
            duplicates_removed += 1
    
    print(f"   Jobs after cleaning: {len(cleaned_jobs)}")
    print(f"   Duplicates removed: {duplicates_removed}")
    print(f"   Invalid jobs removed: {invalid_removed}")

    # 3. Save cleaned jobs back to output file
    with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(cleaned_jobs)
    
    print(f"\n✅ Cleaning completed. Saved {len(cleaned_jobs)} jobs to {csv_file}")


# ============================================================================
# FUNCTION 3: Generate Chinese fields using Gemini AI
# ============================================================================
def process_csv():
    """
    FUNCTION 3: Generate Chinese fields (title_chinese, description_chinese, summary_chinese) using Gemini
    
    Workflow:
    1. Merge input_file (jobs_meta_updated.csv) into output_file (jobs_gemini_edited.csv)
       - Exclude: duplicates, null descriptions, closed jobs
    2. Sort output_file by date (createdAt, newest first)
    3. Process jobs from output_file that don't have title_chinese AND description_chinese
       - Skip jobs with invalid descriptions (< 20 Chinese chars AND < 30 English chars)
       - Call Gemini API to generate Chinese fields
       - Save immediately after each job
    """
    if not os.path.exists(INPUT_FILE):
        print(f"❌ Input file not found: {INPUT_FILE}")
        return

    from util.handle_csv import fieldnames, generate_job_id

    print(f"\n{'='*80}")
    print(f"FUNCTION 3: Generate Chinese fields")
    print(f"{'='*80}\n")

    # PHASE 1: Merge input file into output file
    print("Phase 1: Merging files...")
    
    # 1.1. Load existing output file IDs and duplicate detection data
    existing_output_ids = set()
    seen_title_description = set()
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                job_id = row.get('_id', '')
                if job_id:
                    existing_output_ids.add(job_id)
                
                # Track (title, description) combinations for duplicate detection
                title = row.get('title', '').strip()
                description = row.get('description', '').strip()
                
                if title and description:
                    seen_title_description.add((title, description))
        print(f"📋 Found {len(existing_output_ids)} existing jobs in output file")

    # Phase 1: Read input CSV and merge into output
    new_jobs = []
    excluded_count = 0
    duplicate_count = 0
    invalid_experience_count = 0
    
    with open(INPUT_FILE, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Generate job_id if missing
            job_id = row.get('_id', '')
            if not job_id:
                source_url = row.get('source_url', '')
                if source_url:
                    job_id = generate_job_id(source_url)
                    row['_id'] = job_id
                else:
                    excluded_count += 1
                    continue
            
            # Exclude if ID already in output file
            if job_id in existing_output_ids:
                excluded_count += 1
                continue
            
            # Exclude if description is null/empty
            description = row.get('description', '').strip()
            if not description:
                excluded_count += 1
                continue
            
            # Exclude if "职位已关闭" is in description
            if "职位已关闭" in description:
                excluded_count += 1
                continue
            
            # Exclude if experience is invalid
            experience = row.get('experience', '').strip()
            if not _is_valid_experience(experience):
                invalid_experience_count += 1
                excluded_count += 1
                continue
            
            # Ensure all fields exist
            for field in fieldnames:
                if field not in row:
                    row[field] = ''
            
            # Check for duplicates: same title AND same description
            title = row.get('title', '').strip()
            is_duplicate = False
            
            # Check if (title, description) combination exists (only if both are non-empty)
            if title and description and (title, description) in seen_title_description:
                is_duplicate = True
            
            if is_duplicate:
                duplicate_count += 1
                excluded_count += 1
                continue
            
            # Not a duplicate, add to new_jobs and update tracking set
            new_jobs.append(row)
            if title and description:
                seen_title_description.add((title, description))
    
    print(f"📥 Loaded jobs from input file")
    print(f"   New jobs to add: {len(new_jobs)}")
    other_excluded = excluded_count - duplicate_count - invalid_experience_count
    exclude_details = []
    if duplicate_count > 0:
        exclude_details.append(f"{duplicate_count} duplicates")
    if invalid_experience_count > 0:
        exclude_details.append(f"{invalid_experience_count} invalid experience")
    if other_excluded > 0:
        exclude_details.append(f"{other_excluded} null descriptions/closed jobs")
    exclude_str = ", ".join(exclude_details) if exclude_details else "0"
    print(f"   Excluded: {excluded_count} ({exclude_str})")
    
    # Phase 1: Load existing output rows and merge (filter out invalid experience)
    all_jobs = []
    invalid_output_count = 0
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Ensure all fields exist
                for field in fieldnames:
                    if field not in row:
                        row[field] = ''
                
                # Filter out jobs with invalid experience
                experience = row.get('experience', '').strip()
                if not _is_valid_experience(experience):
                    invalid_output_count += 1
                    continue
                
                all_jobs.append(row)
    
    if invalid_output_count > 0:
        print(f"   ⚠️  Removed {invalid_output_count} jobs from output file (invalid experience)")
    
    # Add new jobs
    all_jobs.extend(new_jobs)
    print(f"   Total jobs in output file: {len(all_jobs)}")
    
    # PHASE 2: Sort by date
    print("Phase 2: Sorting by date...")
    def get_sort_key(job):
        created_at = job.get('createdAt', '')
        if not created_at:
            return datetime.min
        try:
            return datetime.strptime(created_at, "%Y-%m-%d")
        except (ValueError, TypeError):
            return datetime.min
    all_jobs.sort(key=get_sort_key, reverse=True)  # Newest first
    
    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8-sig') as f:
        csv.DictWriter(f, fieldnames=fieldnames).writeheader()
        csv.DictWriter(f, fieldnames=fieldnames).writerows(all_jobs)
    print(f"   ✅ Sorted and saved {len(all_jobs)} jobs")
    
    # PHASE 3: Process jobs from output file
    print("\nPhase 3: Processing jobs...")
    
    # 3.1. Check daily limit
    processed_ids, today_count, _ = _load_processed_status()
    if today_count >= DAILY_LIMIT:
        print(f"⚠️  Daily limit ({DAILY_LIMIT}) reached. Exiting.")
        return
    
    print(f"   Completed: {today_count}/{DAILY_LIMIT}, Remaining: {DAILY_LIMIT - today_count}")
    
    # 3.2. Re-read sorted output file
    with open(OUTPUT_FILE, 'r', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    
    processed_today = 0
    skipped = 0
    failed = 0
    
    # 3.3. Process each job
    for i, row in enumerate(rows, 1):
        if processed_today >= DAILY_LIMIT:
            print(f"\n✅ Daily limit reached. Stopping.")
            break
        
        job_id = row.get('_id', '')
        if not job_id:
            skipped += 1
            continue
        
        # 3.3.1. Skip if already has title_chinese AND description_chinese
        title_chinese = row.get('title_chinese', '').strip()
        description_chinese = row.get('description_chinese', '').strip()
        if title_chinese and description_chinese:
            skipped += 1
            continue
        
        # 3.3.2. Validate description length
        description = row.get('description', '')
        is_valid, invalid_reason = _is_valid_job_description(description)
        if not is_valid:
            skipped += 1
            continue
        
        # 3.3.3. Call Gemini API to generate Chinese fields
        print(f"[{i}/{len(rows)}] {row.get('title', 'N/A')[:50]}")
        result = get_optimized_job_info(row.get('title', ''), row.get('description', ''))
        
        # Check if result is empty (job is not remote) or has no content
        if not result or (isinstance(result, dict) and len(result) == 0):
            skipped += 1
            print(f"    ⏭️  Skipped: Not a remote job (no remote work keywords in title or description)")
            continue
        
        # Check if all key fields are empty (another way Gemini might indicate non-remote job)
        title_chinese = result.get('title_chinese', '').strip() if result else ''
        description_chinese = result.get('description_chinese', '').strip() if result else ''
        if not title_chinese and not description_chinese:
            skipped += 1
            print(f"    ⏭️  Skipped: Not a remote job (all fields empty)")
            continue
        
        if result:
            # 3.3.4. Update row with Gemini results (do not modify title or summary, only add translations)
            row['title_chinese'] = result.get('title_chinese', '')
            row['title_english'] = result.get('title_english', '')
            row['summary_chinese'] = ",".join(result.get('tags_chinese', []))
            row['summary_english'] = ",".join(result.get('tags_english', []))
            row['description_chinese'] = result.get('description_chinese', '')
            row['description_english'] = result.get('description_english', '')
            
            # 3.3.5. Ensure all fields exist (in case some are missing)
            for field in ['title_chinese', 'title_english', 'summary_chinese', 'summary_english', 'description_chinese', 'description_english']:
                if field not in row:
                    row[field] = ''
            
            # 3.3.6. Save to output file
            _update_output_file(job_id, row, fieldnames)
            processed_ids.add(job_id)
            processed_today += 1
        else:
            failed += 1
            # Save with empty Chinese fields
            for field in ['title_chinese', 'summary_chinese', 'description_chinese', 'title_english', 'description_english', 'summary_english']:
                if field not in row:
                    row[field] = ''
            _update_output_file(job_id, row, fieldnames)
            if job_id:
                processed_ids.add(job_id)

        # 3.3.7. Wait between jobs
        if i < len(rows) and processed_today < DAILY_LIMIT:
            time.sleep(DELAY_BETWEEN_JOBS)

    # 3.4. Summary
    print(f"\n✅ Completed: {processed_today} processed, {skipped} skipped, {failed} failed")