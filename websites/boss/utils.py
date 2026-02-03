import re
from typing import Tuple


def is_valid_experience(experience: str) -> bool:
    if not experience:
        return False
    
    experience = experience.strip()
    
    if experience == '经验不限':
        return True
    
    pattern1 = r'^\d+-\d+年$'
    if re.match(pattern1, experience):
        return True
    
    if experience == '1年以内':
        return True
    
    pattern3 = r'^\d+年以上$'
    if re.match(pattern3, experience):
        return True
    
    return False


def is_valid_job_description(description: str) -> Tuple[bool, str]:
    if not description:
        return False, "Description is empty"
    
    chinese_punct = '，。！？；：""''（）【】《》…—、·【】「」『』〈〉《》'
    english_punct = '!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~'
    all_punct = chinese_punct + english_punct
    
    text_no_punct = description.translate(str.maketrans('', '', all_punct))
    
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', text_no_punct)
    english_chars = re.findall(r'[a-zA-Z0-9]', text_no_punct)
    
    chinese_count = len(chinese_chars)
    english_count = len(english_chars)
    
    if chinese_count < 20 and english_count < 30:
        reason = f"Description too short: {chinese_count} Chinese chars, {english_count} English chars (need >= 20 Chinese OR >= 30 English)"
        return False, reason
    
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
        # 保持原有的简单替换逻辑（针对日/周等）
        salary_english = salary
        salary_english = re.sub(r'元/天', '/day', salary_english)
        salary_english = re.sub(r'元/月', '/mo', salary_english) # 理论上上面已经处理了，这里留作备份
        salary_english = re.sub(r'元/周', '/wk', salary_english)
        salary_english = re.sub(r'(\d+)薪', r'\1 pays/yr', salary_english)
    
    return salary_english.strip()

