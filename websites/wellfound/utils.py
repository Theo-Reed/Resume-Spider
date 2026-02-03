import re
from typing import Tuple


def is_valid_experience(experience: str) -> bool:
    if not experience:
        return False
    
    experience = experience.strip().lower()
    
    # English experience patterns
    if 'year' in experience or 'yr' in experience:
        return True
    
    if 'no experience' in experience or 'any' in experience or 'intern' in experience:
        return True
    
    # Numeric patterns like "3+" or "3-5"
    if re.search(r'\d+\+?', experience):
        return True

    # Chinese residue (keep for compatibility if needed, but simplified)
    if '年' in experience or '经验不限' in experience:
        return True
    
    return False


def is_valid_job_description(description: str) -> Tuple[bool, str]:
    if not description:
        return False, "Description is empty"
    
    # Basic length check for English content
    # Wellfound descriptions are usually long. 
    # Let's check for at least 100 characters for a real post.
    if len(description.strip()) < 100:
        return False, f"Description too short ({len(description)} chars)"
    
    # Check if it has enough words (English context)
    words = description.split()
    if len(words) < 20:
        return False, f"Description has too few words ({len(words)})"
    
    return True, ""


def convert_salary_to_english(salary: str) -> str:
    if not salary:
        return ''
    
    salary = salary.strip()
    
    # 特殊处理：如果是 6000-7500元/月 这种格式，转换为 6-7.5K
    if '元/月' in salary:
        # 提取数字部分
        def div_1000(match):
            num = float(match.group(0))
            if num >= 100: # 避免处理已经是 K 的数字
                res = num / 1000
                return f"{res:g}" # :g 去掉多余的 .0
            return match.group(0)
        
        # 替换数字并去掉元/月
        temp = re.sub(r'\d+(\.\d+)?', div_1000, salary)
        salary_english = temp.replace('元/月', 'K').replace('k', 'K')
    else:
        # Wellfound salary usually "$120k – $160k", just keep it or slight cleanup
        salary_english = salary.replace(' – ', '-')
        # 保持原有的简单替换逻辑（针对日/周等）
        salary_english = re.sub(r'元/天', '/day', salary_english)
        salary_english = re.sub(r'元/月', '/mo', salary_english) 
        salary_english = re.sub(r'元/周', '/wk', salary_english)
        salary_english = re.sub(r'(\d+)薪', r'\1 pays/yr', salary_english)
    
    return salary_english.strip()
