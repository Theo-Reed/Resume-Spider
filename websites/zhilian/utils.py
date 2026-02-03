import re
from typing import Tuple


def is_valid_experience(experience: str) -> str:
    """
    归一化经验字段：
    1. 符合数字模式的（1-3年, 3-5年, 1年以下, 10年以上等）返回原文字
    2. '经验不限'、'无经验'、以及其他任何文字，统一返回 '经验不限'
    """
    if not experience:
        return "经验不限"
    
    experience = experience.strip()
    
    # 模式 1: 数字范围 (如 3-5年, 1-3年)
    if re.search(r'\d+-\d+年', experience):
        return experience
    
    # 模式 2: X年以上 (如 5年以上, 10年以上)
    if re.search(r'\d+年以上', experience):
        return experience
    
    # 模式 3: X年以下/以内 (如 1年以下, 3年以内)
    if re.search(r'\d+年以[下内]', experience):
        return experience

    # 其他所有情况（包括 经验不限、无经验、或者乱码/其他文字）
    return "经验不限"


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


def convert_salary_to_english(salary: str, to_english: bool = True) -> str:
    if not salary:
        return ''
    
    salary = salary.strip()
    
    # 1. 检查特殊结尾（时/天/周），这些不按照 K 转换
    if any(x in salary for x in ['时', '天', '周']):
        salary_processed = salary
        if to_english:
            salary_processed = re.sub(r'元/天', '/day', salary_processed)
            salary_processed = re.sub(r'元/周', '/wk', salary_processed)
            salary_processed = re.sub(r'元/时', '/hr', salary_processed)
        return salary_processed.strip()

    # 2. 处理 "万" (例如 2.1-4万 -> 21-40k)
    if '万' in salary:
        def multiply_10(match):
            num = float(match.group(0))
            res = num * 10
            return f"{res:g}"
        temp = re.sub(r'\d+(\.\d+)?', multiply_10, salary)
        salary = temp.replace('万', 'k')

    # 3. 处理 "元" (例如 4000-8000元 -> 4-8k)
    elif '元' in salary:
        def div_1000(match):
            num = float(match.group(0))
            if num >= 500: # 较大的数字认为是月薪，除以 1000
                res = num / 1000
                return f"{res:g}"
            return match.group(0)
        temp = re.sub(r'\d+(\.\d+)?', div_1000, salary)
        salary = temp.replace('元', 'k')

    # 4. 统一清理格式
    salary_processed = salary.lower()
    salary_processed = re.sub(r'元/月', 'k', salary_processed)
    
    if to_english:
        salary_processed = re.sub(r'(\d+)薪', r'\1 pays/yr', salary_processed)
    
    return salary_processed.strip()
