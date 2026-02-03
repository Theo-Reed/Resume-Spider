"""
Salary extraction and conversion utilities
"""

import re
import math


def convert_yearly_to_monthly_salary(salary_text: str) -> str:
    """
    Convert yearly salary to monthly salary.
    Input format: '💰 $70k - $95k' or '$70k - $95k' or '70k - 95k'
    Output format: '$5800-8000' (floor lower, ceil upper, simplified)

    Args:
        salary_text: Salary text in yearly format

    Returns:
        Monthly salary in simplified format
    """
    if not salary_text:
        return ""

    # Remove currency symbols and emojis
    salary_text = salary_text.replace('💰', '').strip()

    # Extract numbers (with k suffix)
    matches = re.findall(r'(\d+(?:\.\d+)?)\s*k?', salary_text.lower())

    if len(matches) < 2:
        return ""

    try:
        # Parse the two numbers
        lower_yearly = float(matches[0])
        upper_yearly = float(matches[1])

        # Handle 'k' values (convert to thousands)
        if lower_yearly < 1000:  # Likely in thousands
            lower_yearly *= 1000
        if upper_yearly < 1000:
            upper_yearly *= 1000

        # Convert to monthly (divide by 12)
        lower_monthly = lower_yearly / 12
        upper_monthly = upper_yearly / 12

        # Floor lower, ceil upper
        lower_monthly = math.floor(lower_monthly / 100) * 100  # Floor to nearest 100
        upper_monthly = math.ceil(upper_monthly / 100) * 100   # Ceil to nearest 100

        return f"${int(lower_monthly)}-{int(upper_monthly)}"

    except (ValueError, IndexError):
        return ""


def extract_salary(description: str) -> tuple:
    """
    Extract salary from job description and return cleaned description.
    Returns: (salary, cleaned_description)
    Handles formats like:
    - '7-8k' or '7-8K'
    - '日薪 300-500 元' (daily wage)
    - '时薪 50-200 元' (hourly wage)
    - '￥7000-8000' or similar
    """
    if not description:
        return "", description

    original_description = description

    # Pattern 0.5: Dollar amounts like '$2500-$3000' formatted as '$2,500-3,000'
    match = re.search(r'\$\s*(\d+)\s*-\s*\$?\s*(\d+)', description)
    if match:
        amount1 = int(match.group(1))
        amount2 = int(match.group(2))
        # Format with commas
        salary = f"${amount1:,}-{amount2:,}"
        cleaned = re.sub(r'\$\s*\d+\s*-\s*\$?\s*\d+', '', description).strip()
        return salary, cleaned

    # Pattern 0: Estimated monthly salary '预估月薪 7k', '预估月薪 10-15k'
    match = re.search(r'预估月薪\s*(\d+\s*-?\s*\d*\s*[kK])', description)
    if match:
        salary_raw = match.group(1).replace(' ', '')
        salary = f"约{salary_raw}"
        cleaned = re.sub(r'预估月薪\s*\d+\s*-?\s*\d*\s*[kK]', '', description).strip()
        return salary, cleaned

    # Pattern 1: Standard format like '7-8k', '7-8K'
    match = re.search(r'(\d+\s*-\s*\d+\s*[kK])', description)
    if match:
        salary = match.group(1)
        cleaned = re.sub(r'\s*' + re.escape(salary) + r'\s*', ' ', description).strip()
        return salary, cleaned

    # Pattern 2: Daily wage '日薪 300-500 元', '日薪 200 元', '日薪 300-500', '日薪 200'
    match = re.search(r'日薪\s*(\d+\s*-?\s*\d*)\s*元?', description)
    if match:
        salary_value = match.group(1).replace(' ', '')
        salary = f"日薪 {salary_value} 元"
        cleaned = re.sub(r'日薪\s*\d+\s*-?\s*\d*\s*元?', '', description).strip()
        return salary, cleaned

    # Pattern 3: Hourly wage '时薪 50-200 元', '时薪 110 元', '时薪 50-200', '时薪 110'
    match = re.search(r'时薪\s*(\d+\s*-?\s*\d*)\s*元?', description)
    if match:
        salary_value = match.group(1).replace(' ', '')
        salary = f"时薪 {salary_value} 元"
        cleaned = re.sub(r'时薪\s*\d+\s*-?\s*\d*\s*元?', '', description).strip()
        return salary, cleaned

    # Pattern 4: Weekly wage '周薪 2000-3000 元' or '周薪 2000-3000'
    match = re.search(r'周薪\s*(\d+\s*-\s*\d+)\s*元?', description)
    if match:
        salary = f"周薪 {match.group(1)} 元"
        cleaned = re.sub(r'周薪\s*\d+\s*-\s*\d+\s*元?', '', description).strip()
        return salary, cleaned

    # Pattern 5: Currency format - 4+ digits, no Chinese context '￥7000-8000' or '1000-8000'
    match = re.search(r'(?<![a-zA-Z0-9\u4e00-\u9fff])\d{4,}\s*-\s*\d{4,}(?![a-zA-Z0-9\u4e00-\u9fff])', description)
    if match:
        salary_match = match.group(0)
        salary = salary_match.replace(' ', '')
        cleaned = re.sub(r'(?<![a-zA-Z0-9\u4e00-\u9fff])\d{4,}\s*-\s*\d{4,}(?![a-zA-Z0-9\u4e00-\u9fff])', '',
                         description).strip()
        return salary, cleaned

    # Pattern 6: Remove "待遇不明" (salary not specified)
    cleaned = re.sub(r'待遇不明', '', description).strip()
    if cleaned != original_description:
        return "", cleaned

    return "", original_description

