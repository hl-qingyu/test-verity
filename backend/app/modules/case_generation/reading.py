"""Organize frozen case-generation inputs for the existing read-only CLI filesystem."""

import json

from app.modules.case_generation import compact
from app.modules.requirements import analysis_materials

GUIDANCE = (
    "先读全部目录页和任务范围，再结合来源元数据逐个读取每份资料的页面或片段。"
    "按固定来源和片段标识关联正文、图片及现有用例。未能读取的范围应写入说明，complete 保持 false。"
)


def reading_layout(data: dict, attachments: list) -> list[dict]:
    files = [
        {
            "path": "task.json",
            "description": "固定任务范围、对照用例、历史和澄清",
            "text": json.dumps(compact.model_task(data), ensure_ascii=False),
        }
    ]
    files.extend(analysis_materials.reading_files(data["materials"], attachments))
    return files
