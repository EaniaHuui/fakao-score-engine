import re
import json
import time
import random
import base64
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import urllib.request
import urllib.error
import urllib.parse
import argparse
from pathlib import Path


ZHUMA_HOME = "https://www.zhumavip.com/"
ZHUMA_PROBE = "https://www.zhumavip.com/java-api/api/p3/question/list/questionTypeV2?businessType=104&kindId=1&legalQuestionType=0&mineType=01&parentTypeId=0"


def chrome_executable(value=None):
    candidates = [value] if value else []
    candidates.extend([
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "google-chrome",
        "chromium",
        "chromium-browser",
        "msedge",
    ])
    for candidate in candidates:
        if not candidate:
            continue
        if "/" in candidate:
            if Path(candidate).is_file():
                return candidate
        elif shutil.which(candidate):
            return candidate
    raise SystemExit("找不到 Chrome、Chromium 或 Edge。请安装其中一个，或通过 --chrome-path 指定浏览器可执行文件。")


def free_local_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def read_exact(connection, size):
    chunks = []
    remaining = size
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise OSError("浏览器调试连接已关闭。")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def websocket_connect(url):
    parsed = urllib.parse.urlparse(url)
    connection = socket.create_connection((parsed.hostname, parsed.port or 80), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    path = parsed.path + ("?" + parsed.query if parsed.query else "")
    request = (
        "GET {} HTTP/1.1\r\n"
        "Host: {}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Key: {}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    ).format(path, parsed.netloc, key)
    connection.sendall(request.encode("ascii"))
    response = b""
    while b"\r\n\r\n" not in response:
        response += connection.recv(4096)
    if not response.startswith(b"HTTP/1.1 101"):
        connection.close()
        raise OSError("无法连接浏览器调试接口。")
    return connection


def websocket_send(connection, value):
    data = json.dumps(value, ensure_ascii=False).encode("utf-8")
    mask = os.urandom(4)
    length = len(data)
    if length < 126:
        header = bytes([0x81, 0x80 | length])
    elif length <= 0xFFFF:
        header = bytes([0x81, 0x80 | 126]) + struct.pack("!H", length)
    else:
        header = bytes([0x81, 0x80 | 127]) + struct.pack("!Q", length)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
    connection.sendall(header + mask + masked)


def websocket_receive(connection):
    first, second = read_exact(connection, 2)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", read_exact(connection, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", read_exact(connection, 8))[0]
    mask = read_exact(connection, 4) if masked else b""
    data = read_exact(connection, length)
    if masked:
        data = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
    if opcode == 0x8:
        return None
    if opcode == 0x9:
        connection.sendall(bytes([0x8A, len(data)]) + data)
        return websocket_receive(connection)
    if opcode != 0x1:
        return websocket_receive(connection)
    return json.loads(data.decode("utf-8"))


def debug_pages(port):
    with urllib.request.urlopen("http://127.0.0.1:{}/json/list".format(port), timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_debugger(port, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            return debug_pages(port)
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            time.sleep(0.5)
    raise SystemExit("浏览器启动超时，未能连接本地调试接口。")


def zhuma_page(pages):
    candidates = [page for page in pages if page.get("type") == "page" and "zhumavip.com" in page.get("url", "")]
    if not candidates:
        raise SystemExit("未找到竹马页面。请在弹出的浏览器窗口中打开竹马网站后重试。")
    return candidates[-1]


def capture_session_headers(port, timeout=20):
    page = zhuma_page(debug_pages(port))
    connection = websocket_connect(page["webSocketDebuggerUrl"])
    try:
        websocket_send(connection, {"id": 1, "method": "Network.enable"})
        websocket_send(connection, {"id": 2, "method": "Runtime.evaluate", "params": {"expression": "fetch({!r}, {{credentials: 'include'}}).catch(() => null)".format(ZHUMA_PROBE)}})
        deadline = time.time() + timeout
        while time.time() < deadline:
            connection.settimeout(max(0.1, deadline - time.time()))
            try:
                message = websocket_receive(connection)
            except socket.timeout:
                continue
            if not message or message.get("method") != "Network.requestWillBeSentExtraInfo":
                continue
            params = message.get("params", {})
            headers = params.get("headers", {})
            if not any(key.lower() in {"cookie", "token", "authorization"} for key in headers):
                continue
            return usable_headers({str(key): str(value) for key, value in headers.items()})
    finally:
        connection.close()
    raise SystemExit("未捕获到有效登录态。请确认已在弹出的竹马窗口中完成登录，再重试。")


def browser_login_headers(chrome_path=None):
    profile_dir = Path(tempfile.mkdtemp(prefix="fakao-zhuma-browser-"))
    port = free_local_port()
    command = [
        chrome_executable(chrome_path),
        "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port={}".format(port),
        "--user-data-dir={}".format(profile_dir),
        "--no-first-run",
        "--no-default-browser-check",
        ZHUMA_HOME,
    ]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_for_debugger(port)
        print("已打开临时竹马浏览器。请在窗口内自行完成登录和验证码，然后回到这里按回车继续。")
        input()
        headers = capture_session_headers(port)
        print("已获取本次会话，正在开始导出；登录态不会写入项目文件。")
        return headers
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        shutil.rmtree(profile_dir, ignore_errors=True)

def parse_curl(curl_str):
    headers = {}
    lines = curl_str.strip().split('\n')
    for line in lines:
        line = line.strip()
        if line.endswith('\\'):
            line = line[:-1].strip()
        match = re.search(r"-[Hh]\s+'([^:]+):\s*(.+?)'", line)
        if match:
            headers[match.group(1)] = match.group(2)
        match_b = re.search(r"-b\s+'([^']+)'", line)
        if match_b:
            headers['cookie'] = match_b.group(1)
    return headers


def usable_headers(headers):
    allowed = {"accept", "authorization", "cookie", "origin", "referer", "token", "user-agent"}
    return {key: value for key, value in headers.items() if key.lower() in allowed}


def has_credentials(headers):
    return any(key.lower() in {"authorization", "cookie", "token"} and value for key, value in headers.items())

def request_json(url, payload, headers):
    data = json.dumps(payload).encode('utf-8') if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method='POST' if payload else 'GET')
    if payload:
        req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req) as response:
            res_body = response.read().decode('utf-8')
            return json.loads(res_body)
    except urllib.error.URLError as e:
        print(f"请求失败: {e}")
        return None

def fetch_top_level(mine_type, headers):
    url = f"https://www.zhumavip.com/java-api/api/p3/question/list/questionTypeV2?businessType=104&kindId=1&legalQuestionType=0&mineType=01&parentTypeId=0"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            res_body = response.read().decode('utf-8')
            return json.loads(res_body)
    except Exception as e:
        print(f"获取顶级分类失败: {e}")
        return None

def format_questions_to_markdown(questions, catalog_name, output_dir, mine_type_name):
    if not questions:
        return
    
    os.makedirs(output_dir, exist_ok=True)
    # 过滤掉非法字符
    safe_name = "".join([c for c in catalog_name if c.isalpha() or c.isdigit() or c in ' -_()[]（）【】']).strip()
    filename = f"{safe_name}_{mine_type_name}导出.md"
    file_path = os.path.join(output_dir, filename)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(f'# {catalog_name} {mine_type_name}集\n\n')
        f.write(f'> 共导出 {len(questions)} 道题目。自动抓取生成。\n\n')
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
                
                checkbox = '[ ]'
                marks = []
                if opt_id in correct_answers:
                    checkbox = '[x]'
                    marks.append('✅ 正确答案')
                if mine_type_name not in ['官方题库', '历年真题'] and opt_id in user_answers:
                    marks.append('❌ 我的答案')
                    
                mark_str = f" **({', '.join(marks)})**" if marks else ""
                f.write(f'- {checkbox} {opt_id}. {opt_text}{mark_str}\n')
            f.write('\n---\n\n')
    print(f"✅ 已导出 {len(questions)} 题至 {file_path}")


def pull_personal_data(headers, mine_type, mine_type_name, output_dir):
    top_res = fetch_top_level(mine_type, headers)
    if not top_res or top_res.get('code') != 200:
        print("❌ 获取大类失败，可能是 Token 过期。")
        return
        
    types = top_res.get('data', [])
    if not types:
        print("⚠️ 未找到任何大类数据。")
        return
        
    for t in types:
        question_type_id = t['id']
        cat_id = t['catalogId']
        print(f"\n📁 正在分析大类: {t['name']}")
        
        if mine_type == '01':
            cat_url = "https://www.zhumavip.com/java-api/api/error/question/list/selectCatalogByUserIdV2"
        elif mine_type == '02':
            cat_url = "https://www.zhumavip.com/java-api/api/collection/question/listByKnowledgePoints"
        else:
            cat_url = "https://www.zhumavip.com/java-api/api/note/question/list/selectCatalogByUserIdV2"
            
        cat_payload = {
            "catId": cat_id,
            "kindId": "1",
            "mineType": mine_type,
            "pageNum": 1,
            "pageSize": 50,
            "questionTypeId": question_type_id,
            "includeSingleJudgeQuestions": True
        }
        
        cat_res = request_json(cat_url, cat_payload, headers)
        if not cat_res or cat_res.get('code') != 200:
            continue
            
        subjects = cat_res.get('data', [])
        for subj in subjects:
            subject_id = subj['id']
            subject_name = subj['content']
            count = subj.get('count', 0)
            
            if count == 0:
                continue
                
            print(f"  -> 发现学科: {subject_name} (包含 {count} 题)，准备拉取...")
            
            if mine_type == '01':
                q_url = "https://www.zhumavip.com/java-api/api/error/question/getQuestionSetFromKnowledgeListV2"
            else:
                q_url = "https://www.zhumavip.com/java-api/api/question/v2/getQuestionSetFromKnowledgeList"
                
            all_questions = []
            page_num = 1
            while True:
                q_payload = {
                    "mineType": mine_type,
                    "kindId": "1",
                    "catalogId": str(subject_id),
                    "questionTypeId": str(question_type_id),
                    "businessTypeId": "104",
                    "includeSingleJudgeQuestions": True,
                    "pageNum": page_num,
                    "pageSize": 50
                }
                
                time.sleep(random.uniform(1.5, 3.0)) 
                q_res = request_json(q_url, q_payload, headers)
                if not q_res or q_res.get('code') != 200:
                    break
                    
                page_data = q_res.get('data', {})
                if isinstance(page_data, list):
                    batch = page_data
                elif isinstance(page_data, dict):
                    batch = page_data.get('questions', [])
                else:
                    batch = []
                    
                if not batch:
                    break
                    
                all_questions.extend(batch)
                print(f"    ... 已获取 {len(all_questions)}/{count} 题")
                
                if len(all_questions) >= count or len(batch) < 50:
                    break
                    
                page_num += 1
                
            format_questions_to_markdown(all_questions, subject_name, output_dir, mine_type_name)

def pull_official_bank(headers, output_dir):
    print("\n⚠️ 准备全量抓取官方章节题库，这可能需要较长时间，并有一定几率触发风控。")
    print("我们将采用 3-300 秒的随机安全抓取间隔。")
    
    top_res = fetch_top_level('01', headers)
    if not top_res or top_res.get('code') != 200:
        print("❌ 获取大类配置失败。")
        return
        
    types = top_res.get('data', [])
    
    for t in types:
        question_type_id = t['id']
        parent_id = t['catalogId']
        print(f"\n📁 正在分析大类: {t['name']} (ID: {parent_id})")
        
        url = f"https://www.zhumavip.com/java-api/api/office/question/catalog/listCatalogByParentIdWithUserInfo?parentId={parent_id}&questionTypeId={question_type_id}&kindId=1&typeId=104"
        time.sleep(random.uniform(1.5, 3.0))
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req) as response:
                cat_res = json.loads(response.read().decode('utf-8'))
        except Exception as e:
            print(f"获取学科列表失败: {e}")
            continue
            
        if cat_res.get('code') != 200:
            print("学科列表返回错误。")
            continue
            
        subjects = cat_res.get('data', [])
        for subj in subjects:
            subject_id = subj['id']
            subject_name = subj['content']
            count = subj.get('count', 0)
            
            if count == 0:
                continue
                
            print(f"  -> 发现学科: {subject_name} (包含 {count} 题)，准备安全拉取...")
            
            all_questions = []
            page_num = 1
            
            q_url = "https://www.zhumavip.com/java-api/api/question/v2/selectByCatalogId"
            
            while True:
                q_payload = {
                    "catalogId": str(subject_id),
                    "questionTypeId": str(question_type_id),
                    "businessTypeId": "104",
                    "includeSingleJudgeQuestions": True,
                    "pageNum": page_num,
                    "pageSize": 50
                }
                
                time.sleep(random.uniform(3.0, 300.0))
                q_res = request_json(q_url, q_payload, headers)
                if not q_res or q_res.get('code') != 200:
                    break
                    
                page_data = q_res.get('data', {})
                batch = page_data.get('questions', []) if isinstance(page_data, dict) else []
                    
                if not batch:
                    break
                    
                all_questions.extend(batch)
                print(f"    ... 已获取 {len(all_questions)}/{count} 题")
                
                if len(all_questions) >= count or len(batch) < 50:
                    break
                    
                page_num += 1
                
            format_questions_to_markdown(all_questions, subject_name, output_dir, "官方题库")

def process_past_exam_catalog(headers, type_id, parent_id, question_type_id, output_dir, path_prefix=""):
    url_catalog = "https://www.zhumavip.com/java-api/api/p3/question/list/appCatalog"
    payload_catalog = {
        "typeId": type_id,
        "parentId": parent_id,
        "questionTypeId": question_type_id,
        "kindId": "2",
        "legalQuestionType": 0
    }
    
    time.sleep(random.uniform(10.0, 60.0))
    cat_res = request_json(url_catalog, payload_catalog, headers)
    
    if not cat_res or cat_res.get('code') != 200:
        return
        
    items = cat_res.get('data', [])
    
    def process_node(node, current_path):
        name = node.get('content', '未知')
        current_id = node.get('id')
        sub_list = node.get('subList', [])
        
        full_name = f"{current_path}-{name}" if current_path else name
        
        if sub_list:
            print(f"📂 发现年份目录: {full_name}，继续下探...")
            for sub_node in sub_list:
                process_node(sub_node, full_name)
        else:
            print(f"  -> 发现真题试卷: {full_name}，准备获取题目...")
            
            q_url = "https://www.zhumavip.com/java-api/api/question/v2/selectByCatalogId"
            q_payload = {
                "code": 2, "kindId": 2, "businessTypeId": 104, 
                "catalogId": current_id, "questionTypeId": question_type_id,
                "againOrContinue": 0, "knowledgePracticeVersion": True
            }
            
            time.sleep(random.uniform(10.0, 60.0))
            q_res = request_json(q_url, q_payload, headers)
            if not q_res or q_res.get('code') != 200:
                print("     (请求试卷信息失败)")
                return
                
            data = q_res.get('data', {})
            answer_id = str(data.get('id', ''))
            
            # 无论 questions 里有多少，都以 questionsIds 为准去拉取全量
            q_ids = [q['id'] for q in data.get('questionsIds', [])]
            if not q_ids:
                # 兼容可能的特殊情况
                questions = data.get('questions', [])
            else:
                print(f"     (本卷共 {len(q_ids)} 题，正在分批完整获取...)")
                all_q = []
                for i in range(0, len(q_ids), 50):
                    batch_ids = q_ids[i:i+50]
                    gl_url = "https://www.zhumavip.com/java-api/api/question/v2/getQuestionList"
                    gl_payload = {
                        "answerId": answer_id,
                        "questionIds": batch_ids,
                        "isBegin": 0
                    }
                    time.sleep(random.uniform(5.0, 15.0))
                    gl_res = request_json(gl_url, gl_payload, headers)
                    if gl_res and gl_res.get('code') == 200:
                        gl_data = gl_res.get('data', {})
                        if isinstance(gl_data, list):
                            batch = gl_data
                        elif isinstance(gl_data, dict):
                            batch = gl_data.get('questions', [])
                        else:
                            batch = []
                        all_q.extend(batch)
                questions = all_q
            
            if questions:
                format_questions_to_markdown(questions, full_name, output_dir, "历年真题")

    for item in items:
        process_node(item, path_prefix)

def pull_past_exams(headers, output_dir):
    print("\n⚠️ 准备抓取历年真题...")
    # 默认历年真题的 parentId=270, questionTypeId=705 (根据用户抓包记录)
    process_past_exam_catalog(headers, 104, 270, 705, output_dir)


def read_curl(curl_file):
    if curl_file:
        return Path(curl_file).read_text(encoding='utf-8')
    print("请输入竹马 cURL，结束时单独输入 EOF：")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == 'EOF':
            break
        lines.append(line)
    return '\n'.join(lines)


def run_export(curl_file=None, mode=None, output_dir=None, browser_login=False, chrome_path=None):
    if browser_login:
        headers = browser_login_headers(chrome_path)
    else:
        curl_str = read_curl(curl_file)
        headers = usable_headers(parse_curl(curl_str))
    if not has_credentials(headers):
        raise SystemExit("解析失败：未能从 cURL 中提取 token 或 cookie。")

    root = Path(__file__).resolve().parents[2]
    defaults = {
        'official': root / '02_原始资料库' / '官方题库',
        'past': root / '02_原始资料库' / '真题原卷',
        'mistakes': root / '04_题目训练库' / '错题',
        'favorites': root / '02_原始资料库' / '收藏题库',
        'notes': root / '02_原始资料库' / '笔记',
    }
    if mode is None:
        print("请选择导出类型：1 错题本 2 收藏本 3 笔记 4 官方章节题库 5 历年真题")
        mode = {'1': 'mistakes', '2': 'favorites', '3': 'notes', '4': 'official', '5': 'past'}.get(input('请输入数字: ').strip(), 'mistakes')
    target = (root / output_dir).resolve() if output_dir and not Path(output_dir).is_absolute() else (Path(output_dir).expanduser().resolve() if output_dir else defaults[mode])
    try:
        target.relative_to(root)
    except ValueError:
        raise SystemExit("输出目录必须位于项目目录内: {}".format(root))
    target.mkdir(parents=True, exist_ok=True)
    if mode == 'official':
        pull_official_bank(headers, str(target))
    elif mode == 'past':
        pull_past_exams(headers, str(target))
    else:
        mine = {'mistakes': ('01', '错题'), 'favorites': ('02', '收藏'), 'notes': ('03', '笔记')}[mode]
        pull_personal_data(headers, mine[0], mine[1], str(target))
    print("导出完成：{}".format(target))


def main():
    parser = argparse.ArgumentParser(description='竹马法考资料导出 CLI')
    auth = parser.add_mutually_exclusive_group()
    auth.add_argument('--curl-file', help='保存了浏览器 cURL 的文件；不提供时从标准输入读取')
    auth.add_argument('--browser-login', action='store_true', help='打开临时浏览器，用户登录一次后自动获取本次会话')
    parser.add_argument('--chrome-path', help='Chrome、Chromium 或 Edge 的可执行文件路径；仅与 --browser-login 一起使用')
    parser.add_argument('--mode', choices=['mistakes', 'favorites', 'notes', 'official', 'past'], required=True, help='导出类型')
    parser.add_argument('--output-dir', help='覆盖默认输出目录')
    args = parser.parse_args()
    if args.chrome_path and not args.browser_login:
        parser.error('--chrome-path 只能与 --browser-login 一起使用')
    run_export(args.curl_file, args.mode, args.output_dir, args.browser_login, args.chrome_path)

if __name__ == "__main__":
    main()
