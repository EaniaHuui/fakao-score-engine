import json
import os
import argparse

def main():
    parser = argparse.ArgumentParser(description='将竹马错题 JSON 转换为知识库 Markdown')
    parser.add_argument('input_file', nargs='?', default='zhuma.json', help='竹马接口 JSON 文件')
    parser.add_argument('--output-dir', default=None, help='输出目录，默认写入 04_题目训练库/错题')
    parser.add_argument('--catalog-name', default=None, help='覆盖接口返回的目录名称')
    args = parser.parse_args()
    input_file = args.input_file

    if not os.path.exists(input_file):
        print(f"❌ 找不到文件: {input_file}")
        print("请将抓取到的错题 JSON 保存为 zhuma.json（放在本项目根目录），或者在运行命令时指定文件路径。")
        print("用法: python3 09_导入与处理工具/cli/竹马错题导出工具.py [json文件路径]")
        return

    with open(input_file, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print(f"❌ 文件 {input_file} 不是有效的 JSON 格式。")
            return

    if data.get('code') != 200 or 'data' not in data:
        print("❌ 解析失败：JSON 数据格式不正确，或者接口返回了错误。")
        return

    catalog_name = data['data'].get('catalogName', '综合')
    questions = data['data'].get('questions', [])

    if not questions:
        print("⚠️ 未在数据中找到错题。")
        return

    # 获取当前脚本的绝对路径，推断项目根目录
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    output_dir = args.output_dir or os.path.join(project_root, '04_题目训练库', '错题')
    
    # 如果目录不存在则创建（兼容防错）
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    catalog_name = args.catalog_name or catalog_name
    output_file = os.path.join(output_dir, f'{catalog_name}_竹马错题导出.md')

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f'# {catalog_name} 错题集 (自动导出)\n\n')
        f.write(f'> 共包含 {len(questions)} 道错题，请重点关注“我的答案”与“正确答案”的偏差，分析出题人陷阱。\n\n')
        f.write('---\n\n')

        for i, q in enumerate(questions, 1):
            q_name = q.get('questionName', '未知来源')
            tag_name = q.get('tagName', '未知题型')
            question_text = q.get('question', '')
            
            f.write(f'## {i}. {q_name} ({tag_name})\n\n')
            f.write(f'**题目:**\n{question_text}\n\n')
            
            options = q.get('options', [])
            correct_answers = q.get('answerArr', [])
            user_answers = q.get('userOptions', [])
            
            f.write('**选项:**\n')
            for opt in options:
                opt_id = opt.get('id', '')
                opt_text = opt.get('text', '')
                
                # 标记状态
                checkbox = '[ ]'
                marks = []
                if opt_id in correct_answers:
                    checkbox = '[x]'
                    marks.append('✅ 正确答案')
                if opt_id in user_answers:
                    marks.append('❌ 我的答案')
                    
                mark_str = f" **({', '.join(marks)})**" if marks else ""
                f.write(f'- {checkbox} {opt_id}. {opt_text}{mark_str}\n')
                
            f.write('\n---\n\n')

    print(f"✅ 成功! {len(questions)} 道错题已导出至:\n{output_file}")

if __name__ == "__main__":
    main()
