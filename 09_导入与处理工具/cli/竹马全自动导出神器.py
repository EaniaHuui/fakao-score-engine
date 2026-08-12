#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""竹马错题全自动导出（两阶段交互 + 凭据落盘 + 接口自修复）

用法：
  python3 竹马全自动导出神器.py auto            # 默认：有有效本地会话直接导出，否则打开浏览器
  python3 竹马全自动导出神器.py open            # 打开临时浏览器后立即返回（不等登录，不挂起）
  python3 竹马全自动导出神器.py login           # 用户登录完成后：取会话 -> 落盘 -> 导出
  python3 竹马全自动导出神器.py close           # 关闭临时浏览器并清理状态
  python3 竹马全自动导出神器.py --chrome-path <path> [action]

设计要点：
1. 两阶段交互：open 只负责弹出浏览器并立即退出；登录态在用户确认后由 login
   阶段取回。进程不会在等待登录时挂起或死亡。
2. 凭据落盘：登录态（cookie 与完整签名头）保存到
   00_系统与用户/zhuma_session.json（该目录已被 .gitignore 保护，权限 600）。
   会话有效期内再次导入无需用户重新登录。
3. 接口自修复：接口返回非 200 时，若浏览器仍打开，自动从浏览器实时请求中
   捕获最新签名头与接口路径，刷新本地会话后重试；自动修复失败才要求重登。
4. 登录判定与接口可用性解耦：登录只看 cookie 中是否存在 stoken/mtoken/token，
   不因接口 404 误判"未登录"。
"""

import json
import time
import random
import base64
import os
import re
import signal
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

# ---------------------------------------------------------------- 常量

ZHUMA_HOME = "https://www.zhumavip.com/"
ZHUMA_API_HOST = "https://www.zhumavip.com/java-api"

# 竹马接口端点（登录会话捕获时若发现真实路径不同，由自修复实时更新并使用）
API_ENDPOINTS = {
    "top_level": ZHUMA_API_HOST + "/api/p3/question/list/questionTypeV2",
    "error_catalog": ZHUMA_API_HOST + "/api/error/question/list/selectCatalogByUserIdV2",
    "error_questions": ZHUMA_API_HOST + "/api/error/question/getQuestionSetFromKnowledgeListV2",
    "collection_catalog": ZHUMA_API_HOST + "/api/collection/question/listByKnowledgePoints",
    "note_catalog": ZHUMA_API_HOST + "/api/note/question/list/selectCatalogByUserIdV2",
    "select_by_catalog": ZHUMA_API_HOST + "/api/question/v2/selectByCatalogId",
    "office_catalog": ZHUMA_API_HOST + "/api/office/question/catalog/listCatalogByParentIdWithUserInfo",
    "app_catalog": ZHUMA_API_HOST + "/api/p3/question/list/appCatalog",
    "question_list": ZHUMA_API_HOST + "/api/question/v2/getQuestionList",
}

ROOT = Path(__file__).resolve().parents[2]
SESSION_FILE = ROOT / "00_系统与用户" / "zhuma_session.json"        # 登录态（gitignore 保护）
BROWSER_STATE_FILE = ROOT / "00_系统与用户" / "zhuma_browser.json"  # 临时浏览器状态

# 请求时丢弃的传输层头（urllib 会自己生成），其余完整保留以通过竹马签名校验
DROP_HEADERS = {"host", "content-length", "connection", "accept-encoding"}

LOGIN_HINT = (
    "👉 请在弹出的浏览器中登录竹马并完成验证码。\n"
    "👉 登录完成后请回复「1」或「我已完成登录」。"
)


# ---------------------------------------------------------------- Chrome / CDP 基础

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


def port_alive(port):
    try:
        debug_pages(port)
        return True
    except Exception:
        return False


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


def ensure_zhuma_page(port):
    """确保存在打开的竹马页面；用户若已关掉竹马标签页则自动导航回去。"""
    try:
        return zhuma_page(debug_pages(port))
    except SystemExit:
        pages = debug_pages(port)
        page = next((p for p in pages if p.get("type") == "page"), None)
        if not page:
            raise
        connection = websocket_connect(page["webSocketDebuggerUrl"])
        try:
            websocket_send(connection, {"id": 1, "method": "Page.navigate", "params": {"url": ZHUMA_HOME}})
        finally:
            connection.close()
        time.sleep(3)
        return zhuma_page(debug_pages(port))


# ---------------------------------------------------------------- 凭据与状态持久化

def load_json_file(path, default=None):
    if not Path(path).is_file():
        return default
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def save_json_file(path, payload):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_session():
    return load_json_file(SESSION_FILE)


def save_session(headers):
    payload = {"captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "headers": headers}
    save_json_file(SESSION_FILE, payload)
    print("🔒 登录态已保存到本地会话文件（下次导入无需重新登录，凭据不会进入仓库）。")


def load_browser_state():
    return load_json_file(BROWSER_STATE_FILE)


def save_browser_state(state):
    save_json_file(BROWSER_STATE_FILE, state)


def clear_browser_state():
    BROWSER_STATE_FILE.unlink(missing_ok=True)


# ---------------------------------------------------------------- 登录判定与会话捕获

def is_logged_in(headers):
    """登录判定只看 cookie 中的登录 token，与接口可用性解耦。"""
    cookie = ""
    for key, value in (headers or {}).items():
        if key.lower() == "cookie":
            cookie = value
            break
    if not cookie:
        return False
    low = cookie.lower()
    return any(marker in low for marker in ("stoken=", "mtoken=", "token="))


def has_credentials(headers):
    return any(key.lower() in {"authorization", "cookie", "token"} and value for key, value in (headers or {}).items())


def capture_live_headers(port, probe_url=None, timeout=15):
    """连接浏览器调试口，注入一次探测请求并捕获完整请求头（含竹马签名头）。

    返回 {"url": 实际请求地址, "headers": 完整请求头}。
    若页面自身正在请求 java-api 接口，优先采用与业务路径匹配的最新请求，
    以便在接口路径变更时自动适配。
    """
    page = ensure_zhuma_page(port)
    connection = websocket_connect(page["webSocketDebuggerUrl"])
    try:
        websocket_send(connection, {"id": 1, "method": "Network.enable"})
        probe = probe_url or API_ENDPOINTS["top_level"]
        websocket_send(connection, {
            "id": 2,
            "method": "Runtime.evaluate",
            "params": {"expression": "fetch({!r}, {{credentials: 'include'}}).catch(() => null)".format(probe)},
        })
        urls, header_list = [], []
        deadline = time.time() + timeout
        while time.time() < deadline:
            connection.settimeout(max(0.1, deadline - time.time()))
            try:
                message = websocket_receive(connection)
            except socket.timeout:
                continue
            if not message:
                continue
            method = message.get("method")
            params = message.get("params", {})
            if method == "Network.requestWillBeSent":
                url = params.get("request", {}).get("url", "")
                if "zhumavip.com/java-api" in url:
                    urls.append(url)
            elif method == "Network.requestWillBeSentExtraInfo":
                headers = {str(k): str(v) for k, v in params.get("headers", {}).items()}
                header_list.append(headers)
        if not header_list:
            raise SystemExit("未捕获到浏览器请求头（调试口可能已断开）。")
        best_headers = header_list[-1]
        probe_path = urllib.parse.urlparse(probe).path
        picked = next((u for u in urls if urllib.parse.urlparse(u).path == probe_path), None)
        if picked is None and urls:
            picked = urls[-1]
        cleaned = {k: v for k, v in best_headers.items() if k.lower() not in DROP_HEADERS}
        return {"url": picked or probe, "headers": cleaned}
    finally:
        connection.close()


# ---------------------------------------------------------------- 自修复请求层

def raw_request(url, payload=None, headers=None, timeout=30):
    """底层请求，任何异常都转成 {'code': ..., 'error': ...} 而不是抛错。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
    req = urllib.request.Request(
        url,
        data=data,
        headers=headers or {},
        method="POST" if payload else "GET",
    )
    if payload:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "ignore")
            return json.loads(body) if body.strip() else {"code": exc.code, "error": str(exc)}
        except json.JSONDecodeError:
            return {"code": exc.code, "error": str(exc)}
    except urllib.error.URLError as exc:
        return {"code": -1, "error": str(exc)}


def api_request(url, payload=None, headers=None):
    """带自修复的接口调用。

    失败（非 code==200）时依次尝试：
      1) 浏览器仍打开 → 实时捕获最新签名头/接口路径 → 刷新本地会话 → 重试
      2) 原会话重试一次（防瞬时抖动）
    自动修复无效才返回原始失败结果，由上层决定是否要求重新登录。
    """
    resp = raw_request(url, payload, headers)
    if resp and resp.get("code") == 200:
        return resp

    print("🔧 接口返回异常（{}），尝试自修复...".format(resp.get("code", "?") if resp else "无响应"))
    state = load_browser_state()
    if state and port_alive(state.get("port")):
        try:
            live = capture_live_headers(state["port"], url)
        except SystemExit as exc:
            print("  （无法从浏览器捕获实时会话：{}）".format(exc))
            live = None
        if live and live.get("headers") and is_logged_in(live["headers"]):
            save_session(live["headers"])
            retried = raw_request(live.get("url", url), payload, live["headers"])
            if retried and retried.get("code") == 200:
                print("✅ 自修复成功：已从浏览器刷新会话并重试通过。")
                return retried
            print("⚠️ 已刷新会话，但重试仍未成功（可能接口路径已变更或风控）。")

    retry = raw_request(url, payload, headers)
    if retry and retry.get("code") == 200:
        return retry
    return resp


def fetch_top_level(mine_type, headers):
    url = "{}?businessType=104&kindId=1&legalQuestionType=0&mineType={}&parentTypeId=0".format(
        API_ENDPOINTS["top_level"], mine_type
    )
    return api_request(url, headers=headers)


def request_json(url, payload, headers):
    return api_request(url, payload=payload, headers=headers)


# ---------------------------------------------------------------- 导出逻辑

def format_questions_to_markdown(questions, catalog_name, output_dir, mine_type_name):
    if not questions:
        return 0
    os.makedirs(output_dir, exist_ok=True)
    safe_name = "".join([c for c in catalog_name if c.isalpha() or c.isdigit() or c in ' -_()[]（）【】']).strip()
    filename = "{}_{}导出.md".format(safe_name, mine_type_name)
    file_path = os.path.join(output_dir, filename)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write("# {} {}集\n\n".format(catalog_name, mine_type_name))
        f.write("> 共导出 {} 道题目。自动抓取生成。\n\n".format(len(questions)))
        f.write("---\n\n")

        for i, q in enumerate(questions, 1):
            q_name = q.get("questionName", "未知来源")
            tag_name = q.get("tagName", "未知题型")
            question_text = q.get("question", "")

            f.write("## {}. {} ({})\n\n".format(i, q_name, tag_name))
            f.write("**题目:**\n{}\n\n".format(question_text))

            options = q.get("options", [])
            correct_answers = q.get("answerArr", [])
            user_answers = q.get("userOptions", [])

            f.write("**选项:**\n")
            for opt in options:
                opt_id = opt.get("id", "")
                opt_text = opt.get("text", "")

                checkbox = "[ ]"
                marks = []
                if opt_id in correct_answers:
                    checkbox = "[x]"
                    marks.append("✅ 正确答案")
                if mine_type_name not in ("官方题库", "历年真题") and opt_id in user_answers:
                    marks.append("❌ 我的答案")

                mark_str = " **({})**".format(", ".join(marks)) if marks else ""
                f.write("- {} {}. {}{}\n".format(checkbox, opt_id, opt_text, mark_str))
            f.write("\n---\n\n")
    print("✅ 已导出 {} 题至 {}".format(len(questions), file_path))
    return len(questions)


def pull_personal_data(headers, mine_type, mine_type_name, output_dir):
    total = 0
    top_res = fetch_top_level(mine_type, headers)
    if not top_res or top_res.get("code") != 200:
        print("❌ 获取大类失败，登录态可能已失效。")
        return 0

    types = top_res.get("data", [])
    if not types:
        print("⚠️ 未找到任何大类数据。")
        return 0

    for t in types:
        question_type_id = t["id"]
        cat_id = t["catalogId"]
        print("\n📁 正在分析大类: {}".format(t["name"]))

        if mine_type == "01":
            cat_url = API_ENDPOINTS["error_catalog"]
        elif mine_type == "02":
            cat_url = API_ENDPOINTS["collection_catalog"]
        else:
            cat_url = API_ENDPOINTS["note_catalog"]

        cat_payload = {
            "catId": cat_id,
            "kindId": "1",
            "mineType": mine_type,
            "pageNum": 1,
            "pageSize": 50,
            "questionTypeId": question_type_id,
            "includeSingleJudgeQuestions": True,
        }

        cat_res = request_json(cat_url, cat_payload, headers)
        if not cat_res or cat_res.get("code") != 200:
            continue

        subjects = cat_res.get("data", [])
        for subj in subjects:
            subject_id = subj["id"]
            subject_name = subj["content"]
            count = subj.get("count", 0)

            if count == 0:
                continue

            print("  -> 发现学科: {} (包含 {} 题)，准备拉取...".format(subject_name, count))

            if mine_type == "01":
                q_url = API_ENDPOINTS["error_questions"]
            else:
                q_url = API_ENDPOINTS["select_by_catalog"]

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
                    "pageSize": 50,
                }

                time.sleep(random.uniform(1.5, 3.0))
                q_res = request_json(q_url, q_payload, headers)
                if not q_res or q_res.get("code") != 200:
                    break

                page_data = q_res.get("data", {})
                if isinstance(page_data, list):
                    batch = page_data
                elif isinstance(page_data, dict):
                    batch = page_data.get("questions", [])
                else:
                    batch = []

                if not batch:
                    break

                all_questions.extend(batch)
                print("    ... 已获取 {}/{} 题".format(len(all_questions), count))

                if len(all_questions) >= count or len(batch) < 50:
                    break

                page_num += 1

            total += format_questions_to_markdown(all_questions, subject_name, output_dir, mine_type_name)
    return total


def pull_official_bank(headers, output_dir):
    print("\n⚠️ 准备全量抓取官方章节题库，这可能需要较长时间，并有一定几率触发风控。")
    print("我们将采用 3-300 秒的随机安全抓取间隔。")

    top_res = fetch_top_level("01", headers)
    if not top_res or top_res.get("code") != 200:
        print("❌ 获取大类配置失败。")
        return

    types = top_res.get("data", [])

    for t in types:
        question_type_id = t["id"]
        parent_id = t["catalogId"]
        print("\n📁 正在分析大类: {} (ID: {})".format(t["name"], parent_id))

        url = "{}?parentId={}&questionTypeId={}&kindId=1&typeId=104".format(
            API_ENDPOINTS["office_catalog"], parent_id, question_type_id
        )
        time.sleep(random.uniform(1.5, 3.0))
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                cat_res = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            print("获取学科列表失败: {}".format(exc))
            continue

        if cat_res.get("code") != 200:
            print("学科列表返回错误。")
            continue

        subjects = cat_res.get("data", [])
        for subj in subjects:
            subject_id = subj["id"]
            subject_name = subj["content"]
            count = subj.get("count", 0)

            if count == 0:
                continue

            print("  -> 发现学科: {} (包含 {} 题)，准备安全拉取...".format(subject_name, count))

            all_questions = []
            page_num = 1

            q_url = API_ENDPOINTS["select_by_catalog"]

            while True:
                q_payload = {
                    "catalogId": str(subject_id),
                    "questionTypeId": str(question_type_id),
                    "businessTypeId": "104",
                    "includeSingleJudgeQuestions": True,
                    "pageNum": page_num,
                    "pageSize": 50,
                }

                time.sleep(random.uniform(3.0, 300.0))
                q_res = request_json(q_url, q_payload, headers)
                if not q_res or q_res.get("code") != 200:
                    break

                page_data = q_res.get("data", {})
                batch = page_data.get("questions", []) if isinstance(page_data, dict) else []

                if not batch:
                    break

                all_questions.extend(batch)
                print("    ... 已获取 {}/{} 题".format(len(all_questions), count))

                if len(all_questions) >= count or len(batch) < 50:
                    break

                page_num += 1

            format_questions_to_markdown(all_questions, subject_name, output_dir, "官方题库")


def process_past_exam_catalog(headers, type_id, parent_id, question_type_id, output_dir, path_prefix=""):
    url_catalog = API_ENDPOINTS["app_catalog"]
    payload_catalog = {
        "typeId": type_id,
        "parentId": parent_id,
        "questionTypeId": question_type_id,
        "kindId": "2",
        "legalQuestionType": 0,
    }

    time.sleep(random.uniform(10.0, 60.0))
    cat_res = request_json(url_catalog, payload_catalog, headers)

    if not cat_res or cat_res.get("code") != 200:
        return

    items = cat_res.get("data", [])

    def process_node(node, current_path):
        name = node.get("content", "未知")
        current_id = node.get("id")
        sub_list = node.get("subList", [])

        full_name = "{}-{}".format(current_path, name) if current_path else name

        if sub_list:
            print("📂 发现年份目录: {}，继续下探...".format(full_name))
            for sub_node in sub_list:
                process_node(sub_node, full_name)
        else:
            print("  -> 发现真题试卷: {}，准备获取题目...".format(full_name))

            q_url = API_ENDPOINTS["select_by_catalog"]
            q_payload = {
                "code": 2, "kindId": 2, "businessTypeId": 104,
                "catalogId": current_id, "questionTypeId": question_type_id,
                "againOrContinue": 0, "knowledgePracticeVersion": True,
            }

            time.sleep(random.uniform(10.0, 60.0))
            q_res = request_json(q_url, q_payload, headers)
            if not q_res or q_res.get("code") != 200:
                print("     (请求试卷信息失败)")
                return

            data = q_res.get("data", {})
            answer_id = str(data.get("id", ""))

            # 无论 questions 里有多少，都以 questionsIds 为准去拉取全量
            q_ids = [q["id"] for q in data.get("questionsIds", [])]
            if not q_ids:
                # 兼容可能的特殊情况
                questions = data.get("questions", [])
            else:
                print("     (本卷共 {} 题，正在分批完整获取...)".format(len(q_ids)))
                all_q = []
                for i in range(0, len(q_ids), 50):
                    batch_ids = q_ids[i:i + 50]
                    gl_url = API_ENDPOINTS["question_list"]
                    gl_payload = {
                        "answerId": answer_id,
                        "questionIds": batch_ids,
                        "isBegin": 0,
                    }
                    time.sleep(random.uniform(5.0, 15.0))
                    gl_res = request_json(gl_url, gl_payload, headers)
                    if gl_res and gl_res.get("code") == 200:
                        gl_data = gl_res.get("data", {})
                        if isinstance(gl_data, list):
                            batch = gl_data
                        elif isinstance(gl_data, dict):
                            batch = gl_data.get("questions", [])
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


def export_all(headers):
    """导出错题，返回导出的题目总数。"""
    target = ROOT / "04_题目训练库" / "错题"
    target.mkdir(parents=True, exist_ok=True)
    if not has_credentials(headers):
        print("❌ 会话缺少凭据，无法导出。")
        return 0
    return pull_personal_data(headers, "01", "错题", str(target))


# ---------------------------------------------------------------- 浏览器生命周期

def open_browser(chrome_path=None):
    """打开临时竹马浏览器并立即返回（不等待登录，进程不挂起）。"""
    close_browser(quiet=True)
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
    wait_for_debugger(port)
    save_browser_state({
        "port": port,
        "profile_dir": str(profile_dir),
        "pid": process.pid,
        "opened_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    print("✅ 已打开临时竹马浏览器。")


def close_browser(quiet=False):
    """关闭临时浏览器并清理状态文件与临时环境。"""
    state = load_browser_state()
    if not state:
        if not quiet:
            print("没有打开的临时浏览器。")
        return
    pid = state.get("pid")
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
    profile_dir = state.get("profile_dir")
    if profile_dir:
        shutil.rmtree(profile_dir, ignore_errors=True)
    clear_browser_state()
    if not quiet:
        print("已关闭临时浏览器并清理临时环境。")


# ---------------------------------------------------------------- 子命令

def cmd_open(args):
    open_browser(args.chrome_path)
    print(LOGIN_HINT)


def cmd_login(args):
    state = load_browser_state()
    if not state or not port_alive(state.get("port")):
        print("⚠️ 没有找到仍在运行的临时浏览器。请先运行 `./fakao zhuma open`（或直接 `./fakao zhuma`）。")
        raise SystemExit(1)

    print("正在从浏览器读取登录态（若刚完成登录请稍候）...")
    deadline = time.time() + 180
    headers = None
    while time.time() < deadline:
        try:
            live = capture_live_headers(state["port"])
        except SystemExit as exc:
            print("  等待浏览器响应... {}".format(exc))
            time.sleep(2)
            continue
        if live and is_logged_in(live["headers"]):
            headers = live["headers"]
            break
        print("  尚未检测到登录态（可能验证码未完成），继续等待...")
        time.sleep(2)

    if not headers:
        print("❌ 未检测到有效登录态。请确认已在浏览器中完成登录（含验证码），再回复「1」。")
        raise SystemExit(1)

    save_session(headers)
    print("✅ 登录态校验通过。")
    total = export_all(headers)
    if total > 0:
        print("✅ 错题导出完成：共 {} 题，位置 {}".format(total, ROOT / "04_题目训练库" / "错题"))
        print("ℹ️ 临时浏览器会保留，以便下次复用登录态；不需要时可回复「关闭浏览器」。")
    else:
        print("⚠️ 未导出到新错题（详见上方日志）。")
        raise SystemExit(1)


def cmd_auto(args):
    """智能模式：有可用本地会话直接导出；否则打开浏览器并提示用户登录。"""
    session = load_session()
    if session and is_logged_in(session.get("headers", {})):
        print("🔑 发现本地已保存的登录态，直接开始导出（无需重新登录）。")
        total = export_all(session["headers"])
        if total > 0:
            print("✅ 错题导出完成：共 {} 题，位置 {}".format(total, ROOT / "04_题目训练库" / "错题"))
            return
        print("⚠️ 本地会话导出失败，自修复未能恢复，需要重新登录。")

    state = load_browser_state()
    if state and port_alive(state.get("port")):
        print("✅ 检测到已打开的竹马浏览器（端口 {}）。".format(state["port"]))
    else:
        open_browser(args.chrome_path)
    print(LOGIN_HINT)


# ---------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description="导入你自己的竹马错题")
    parser.add_argument(
        "action",
        nargs="?",
        default="auto",
        choices=["auto", "open", "login", "close"],
        help="auto=智能(默认,有会话直接导出) open=打开浏览器 login=登录后导出 close=关闭浏览器",
    )
    parser.add_argument("--chrome-path", help="Chrome、Chromium 或 Edge 的可执行文件路径")
    args = parser.parse_args()

    if args.action == "open":
        cmd_open(args)
    elif args.action == "login":
        cmd_login(args)
    elif args.action == "close":
        close_browser()
    else:
        cmd_auto(args)


if __name__ == "__main__":
    main()
