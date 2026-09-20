import os
import jieba

import config


def search_documents(question):
    results = []

    # 把问题拆成中文词语
    keywords = jieba.lcut(question)

    for filename in os.listdir(config.DOCUMENTS_DIR):
        if not filename.endswith(".md"):
            continue

        filepath = os.path.join(config.DOCUMENTS_DIR, filename)

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # 计算这个文件匹配了多少个关键词
        score = 0

        for keyword in keywords:
            if len(keyword) <= 1:
                continue

            if keyword in content:
                score += 1

        if score > 0:
            results.append({
                "file": filepath,
                "content": content,
                "score": score
            })

    # 匹配关键词越多，越相关
    results.sort(key=lambda x: x["score"], reverse=True)

    return results[:2]