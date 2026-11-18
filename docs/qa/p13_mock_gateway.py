"""Deterministic local SSE fixture; never used by production or real-model acceptance."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
import time


class Gateway(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        context = "\n".join(item["content"] for item in payload["messages"][:2])
        if "当前知识点：条件判断" in context:
            title = "条件判断"
            code = 'stock = 3\nif stock > 0:\n    print("可以借书")\nelse:\n    print("暂无库存")'
            explanation = "stock 是库存，if 根据 stock 是否大于 0 选择分支。预期输出：可以借书。"
        elif "当前知识点：列表与索引" in context:
            title = "列表与索引"
            code = 'books = ["Python", "数据库", "网络"]\nprint(books[0])'
            explanation = "books 保存有序数据，第一个索引是 0。预期输出：Python。"
        else:
            title = "变量与赋值"
            code = "price = 37\nquantity = 2\ntotal = price * quantity\nprint(total)"
            explanation = "price 代表单价，total 是总价。预期输出：74。"
        text = f"## {title}（模拟验收）\n\n这是可控 SSE 测试，不是真实模型输出。\n\n### 完整案例\n\n```python\n{code}\n```\n\n### 逐句解释\n\n{explanation}\n\n数学表达：$stock > 0$。\n\n补充：实际项目会用它来组织数据。"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            for offset in range(0, len(text), 8):
                chunk = {"choices": [{"delta": {"content": text[offset:offset + 8]}}]}
                self.wfile.write(("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n").encode())
                self.wfile.flush()
                time.sleep(0.04)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


def start():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    Thread(target=server.serve_forever, daemon=True).start()
    return server
