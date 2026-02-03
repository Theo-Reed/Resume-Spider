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
_WELLFOUND_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE = os.path.join(_WELLFOUND_DIR, "csv_file", "jobs_meta_updated.csv")
OUTPUT_FILE = os.path.join(_WELLFOUND_DIR, "csv_file", "jobs_gemini_edited.csv")
FINAL_OUTPUT_FILE = os.path.join(_WELLFOUND_DIR, "csv_file", "jobs_final.csv")

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


def get_optimized_job_info(original_title: str, description: str) -> Dict:
    prompt = f"""
<task>
Given <original_title> and <description>, generate the Chinese versions first, then translate them to English.

Workflow:
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

The output MUST be a valid JSON object with EXACT keys:
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
    
    last_error = None
    
    # Simple model loop
    for model_name in MODEL_LIST:
        try:
            current_model = genai.GenerativeModel(model_name)
            response = current_model.generate_content(prompt)
            content = _strip_code_fences(getattr(response, "text", "") or "")
            
            if not content:
                continue
            
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                extracted = extract_json_from_text(content)
                if extracted:
                    return extracted
        except Exception as e:
            last_error = e
            # Check for location error
            error_msg = str(e)
            if "User location is not supported" in error_msg or "400" in error_msg and "location" in error_msg.lower():
                print(f"    ❌ Critical Error: User location is not supported. Please check your VPN/Proxy.")
                raise e # Re-raise to be caught by caller
            
            time.sleep(1) # simple retry backoff
            continue
            
    print(f"    ❌ Gemini failed after trying all models. Last Error: {last_error}")
    return {}
