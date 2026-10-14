"""User-facing labels for professional task records.

Internal task kinds remain stable for routing and persistence. These labels are
only for the UI and history payloads, so implementation names never become a
user-facing requirement.
"""

DISPLAY_TYPES = {
    "tailor_resume": "简历",
    "analyze_job": "分析",
    "quick_analysis": "快速判断",
    "interview_prep": "面试卡",
    "interview_review": "面试复盘",
    "suggest_reply": "HR沟通",
}


def display_type(kind):
    return DISPLAY_TYPES.get(kind, "任务")


def display_name(kind, sequence):
    try:
        number = max(1, int(sequence))
    except (TypeError, ValueError):
        number = 1
    return f"{display_type(kind)} {number}"
