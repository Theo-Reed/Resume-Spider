import json
import os
import re
import time
import warnings
import signal
import traceback
from typing import List, Dict, Any, Optional
import google.generativeai as genai
from dotenv import load_dotenv

warnings.filterwarnings('ignore')

# Load environment variables from .env file
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env'))

GEMINI_TIMEOUT = 120

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
_BOSS_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE = os.path.join(_BOSS_DIR, "csv_file", "jobs_meta_updated.csv")
OUTPUT_FILE = os.path.join(_BOSS_DIR, "csv_file", "jobs_gemini_edited.csv")
FINAL_OUTPUT_FILE = os.path.join(_BOSS_DIR, "csv_file", "jobs_final.csv")

genai.configure(api_key=GEMINI_API_KEY)

MODEL_LIST = [
    'gemini-3-flash-preview',
    'gemini-2.5-pro',
]

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
    if not text:
        return None
    
    try:
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
    global _current_model_index
    
    if _current_model_index is not None and _current_model_index < len(MODEL_LIST):
        model_name = MODEL_LIST[_current_model_index]
        return model_name
    
    if _current_model_index is None:
        _current_model_index = 0
    
    if _current_model_index >= len(MODEL_LIST):
        return None
    
    return MODEL_LIST[_current_model_index]


def _switch_to_next_model() -> Optional[str]:
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
        
        def _timeout_handler(signum, frame):
            raise TimeoutError(f"Gemini API call timed out after {GEMINI_TIMEOUT} seconds")
        
        for attempt in range(6):
            try:
                signal.signal(signal.SIGALRM, _timeout_handler)
                signal.alarm(GEMINI_TIMEOUT)
                
                current_model = genai.GenerativeModel(model_name)
                response = current_model.generate_content(p)
                
                if not response:
                    signal.alarm(0)
                    raise ValueError("Gemini returned None response object")
                
                try:
                    content = _strip_code_fences(getattr(response, "text", "") or "")
                except AttributeError:
                    signal.alarm(0)
                    raise ValueError(f"Gemini response object missing 'text' attribute. Response type: {type(response)}")
                except Exception as e:
                    signal.alarm(0)
                    raise ValueError(f"Error accessing response.text: {str(e)}")
                
                last_content = content
                signal.alarm(0)
                
                if not content or not isinstance(content, str):
                    raise ValueError(f"Gemini returned invalid response: type={type(content)}, value={repr(content)[:100]}")
                
                try:
                    parsed_result = json.loads(content)
                    if isinstance(parsed_result, dict) and len(parsed_result) == 0:
                        print(f"    ℹ️  Non-remote job detected (empty JSON object returned)")
                        return parsed_result
                    return parsed_result
                except json.JSONDecodeError:
                    extracted = extract_json_from_text(content)
                    if extracted:
                        if isinstance(extracted, dict) and len(extracted) == 0:
                            print(f"    ℹ️  Non-remote job detected (empty JSON object extracted)")
                            return extracted
                        print(f"    ✅ Fixed JSON by extracting from text (model: {model_name})")
                        return extracted
                    raise
            except TimeoutError as e:
                signal.alarm(0)
                last_error = e
                error_type = "API_TIMEOUT"
                if attempt < 3:
                    print(f"    ⚠️  Attempt {attempt + 1}/6: API timeout (model: {model_name}), retrying...")
                    time.sleep(2)
                    continue
            except json.JSONDecodeError as e:
                signal.alarm(0)
                last_error = e
                error_type = "JSON_PARSE"
                if attempt < 3:
                    print(f"    ⚠️  Attempt {attempt + 1}/6: JSON parse error (model: {model_name}), retrying...")
                    print(f"       Response preview: {last_content[:200] if last_content else 'empty'}")
                    time.sleep(2)
                    continue
            except Exception as e:
                signal.alarm(0)
                last_error = e
                msg = str(e).lower()
                
                if "timeout" in msg:
                    error_type = "API_TIMEOUT"
                    if attempt < 3:
                        print(f"    ⚠️  Attempt {attempt + 1}/6: API timeout (model: {model_name}), retrying...")
                        time.sleep(2)
                        continue
                elif "429" in str(e) or "quota" in msg or "rate" in msg:
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
                elif "network" in msg or "connection" in msg:
                    error_type = "API_NETWORK"
                    if attempt < 4:
                        sleep_s = min(30, 3 * (attempt + 1))
                        print(f"    ⚠️  Attempt {attempt + 1}/6: Network error (model: {model_name}), retrying in {sleep_s}s...")
                        time.sleep(sleep_s)
                        continue
                else:
                    error_type = "API_OTHER"
                    if attempt < 2:
                        print(f"    ⚠️  Attempt {attempt + 1}/6: API error ({type(e).__name__}: {e}) (model: {model_name}), retrying...")
                        time.sleep(1)
                        continue
        
        if last_error:
            error_msg = str(last_error)
            if error_type == "JSON_PARSE":
                print(f"    ❌ CODE ISSUE: JSON parsing failed after 6 attempts (model: {model_name})")
                print(f"       Error: {error_msg}")
                print(f"       Last response preview: {last_content[:300] if last_content else 'N/A'}")
            elif error_type == "API_QUOTA":
                print(f"    ❌ GEMINI API ISSUE: Quota/rate limit exceeded after 6 attempts (model: {model_name})")
                print(f"       Error: {error_msg}")
            elif error_type == "API_NETWORK":
                print(f"    ❌ GEMINI API ISSUE: Network/connection problem after 6 attempts (model: {model_name})")
                print(f"       Error: {error_msg}")
            elif error_type == "API_TIMEOUT":
                print(f"    ❌ GEMINI API ISSUE: Request timed out after {GEMINI_TIMEOUT}s after 6 attempts (model: {model_name})")
                print(f"       Error: {error_msg}")
            elif error_type == "API_MODEL_NOT_FOUND":
                print(f"    ❌ GEMINI API ISSUE: Model not found (model: {model_name})")
                print(f"       Error: {error_msg}")
            else:
                print(f"    ❌ GEMINI API ISSUE: {error_type or 'Unknown error'} after 6 attempts (model: {model_name})")
                print(f"       Error: {error_msg}")
                # print(f"       Traceback: {traceback.format_exc()}")
        else:
            print(f"    ❌ Unknown error: exceeded retries without error details (model: {model_name})")
        
        return None

    current_model = _get_current_model()
    if not current_model:
        print(f"    ❌ No available models, all exhausted")
        return None
    
    if _current_model_index == 0:
        print(f"    🤖 Starting with model: {current_model}")
    
    result = None
    max_model_switches = len(MODEL_LIST)
    switch_count = 0
    
    while switch_count < max_model_switches and current_model:
        try:
            result = _call_gemini(prompt, current_model)
            if result is not None:
                if isinstance(result, dict) and len(result) == 0:
                    print(f"    ℹ️  Non-remote job (empty result), returning empty dict")
                    return result
                print(f"    ✅ Success with model: {current_model}")
                break
        except Exception as e:
            if "QUOTA_EXHAUSTED" in str(e):
                current_model = _switch_to_next_model()
                if current_model:
                    switch_count += 1
                    print(f"    🔄 Quota exhausted, switched to model: {current_model} (switch {switch_count}/{max_model_switches})")
                    continue
                else:
                    print(f"    ❌ All models exhausted")
                    return None
            else:
                print(f"    ❌ Unexpected error: {e}")
                break
    
    if not result:
        return None
    
    if isinstance(result, dict) and len(result) == 0:
        return result
    
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
    def _call_gemini_translate(p: str, model_name: str) -> Optional[Dict[str, Any]]:
        last_error = None
        error_type = None
        last_content = None
        
        def _timeout_handler(signum, frame):
            raise TimeoutError(f"Gemini API call timed out after {GEMINI_TIMEOUT} seconds")
        
        for attempt in range(6):
            try:
                signal.signal(signal.SIGALRM, _timeout_handler)
                signal.alarm(GEMINI_TIMEOUT)
                
                current_model = genai.GenerativeModel(model_name)
                response = current_model.generate_content(p)
                
                if not response:
                    signal.alarm(0)
                    raise ValueError("Gemini returned None response object")
                
                try:
                    content = _strip_code_fences(getattr(response, "text", "") or "")
                except AttributeError:
                    signal.alarm(0)
                    raise ValueError(f"Gemini response object missing 'text' attribute. Response type: {type(response)}")
                except Exception as e:
                    signal.alarm(0)
                    raise ValueError(f"Error accessing response.text: {str(e)}")
                
                last_content = content
                signal.alarm(0)
                
                if not content or not isinstance(content, str):
                    raise ValueError(f"Gemini returned invalid response: type={type(content)}, value={repr(content)[:100]}")
                
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    extracted = extract_json_from_text(content)
                    if extracted:
                        print(f"    ✅ Fixed JSON by extracting from text (model: {model_name})")
                        return extracted
                    raise
            except TimeoutError as e:
                signal.alarm(0)
                last_error = e
                error_type = "API_TIMEOUT"
                if attempt < 3:
                    print(f"    ⚠️  Attempt {attempt + 1}/6: API timeout (model: {model_name}), retrying...")
                    time.sleep(2)
                    continue
            except json.JSONDecodeError as e:
                signal.alarm(0)
                last_error = e
                error_type = "JSON_PARSE"
                if attempt < 3:
                    print(f"    ⚠️  Attempt {attempt + 1}/6: JSON parse error (model: {model_name}), retrying...")
                    print(f"       Response preview: {last_content[:200] if last_content else 'empty'}")
                    time.sleep(2)
                    continue
            except Exception as e:
                signal.alarm(0)
                last_error = e
                msg = str(e).lower()
                
                if "timeout" in msg:
                    error_type = "API_TIMEOUT"
                    if attempt < 3:
                        print(f"    ⚠️  Attempt {attempt + 1}/6: API timeout (model: {model_name}), retrying...")
                        time.sleep(2)
                        continue
                elif "429" in str(e) or "quota" in msg or "rate" in msg:
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
                elif "network" in msg or "connection" in msg:
                    error_type = "API_NETWORK"
                    if attempt < 4:
                        sleep_s = min(30, 3 * (attempt + 1))
                        print(f"    ⚠️  Attempt {attempt + 1}/6: Network error (model: {model_name}), retrying in {sleep_s}s...")
                        time.sleep(sleep_s)
                        continue
                else:
                    error_type = "API_OTHER"
                    if attempt < 2:
                        print(f"    ⚠️  Attempt {attempt + 1}/6: API error ({type(e).__name__}: {e}) (model: {model_name}), retrying...")
                        time.sleep(1)
                        continue
        
        if last_error:
            error_msg = str(last_error)
            if error_type == "JSON_PARSE":
                print(f"    ❌ JSON parsing failed after 6 attempts (model: {model_name})")
                print(f"       Error: {error_msg}")
                print(f"       Last response preview: {last_content[:300] if last_content else 'N/A'}")
            elif error_type == "API_TIMEOUT":
                print(f"    ❌ Translation API error: Request timed out after {GEMINI_TIMEOUT}s after 6 attempts (model: {model_name})")
                print(f"       Error: {error_msg}")
            else:
                print(f"    ❌ Translation API error: {error_type or 'Unknown error'} after 6 attempts (model: {model_name})")
                print(f"       Error: {error_msg}")
        else:
            print(f"    ❌ Unknown error: exceeded retries without error details (model: {model_name})")
        
        return None

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
    
    current_model = _get_current_model()
    if not current_model:
        print(f"    ❌ ERROR: No available models for translation, all models exhausted")
        return None
    
    if _current_model_index == 0:
        print(f"    🤖 Starting translation with model: {current_model}")
    
    result = None
    max_model_switches = len(MODEL_LIST)
    switch_count = 0
    
    while switch_count < max_model_switches and current_model:
        try:
            result = _call_gemini_translate(prompt, current_model)
            if result:
                if 'translations' in result and isinstance(result['translations'], list):
                    print(f"    ✅ SUCCESS: Translation completed with model: {current_model}")
                    print(f"       Received {len(result['translations'])} translation(s)")
                    break
                else:
                    print(f"    ⚠️  WARNING: Translation response missing 'translations' field")
                    result = None
        except Exception as e:
            if "QUOTA_EXHAUSTED" in str(e):
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
        return None
    
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
    
    updated_jobs = []
    missing_count = 0
    for job in jobs_batch:
        job_id = job.get('_id', '')
        if job_id in translations_dict:
            job['title_english'] = translations_dict[job_id]['title_english']
            job['description_english'] = translations_dict[job_id]['description_english']
            job['summary_english'] = translations_dict[job_id]['summary_english']
        else:
            missing_count += 1
            job['title_english'] = ''
            job['description_english'] = ''
            job['summary_english'] = ''
        updated_jobs.append(job)
    
    if missing_count > 0:
        print(f"    ⚠️  WARNING: {missing_count} job(s) missing translations in response")
    
    return updated_jobs
