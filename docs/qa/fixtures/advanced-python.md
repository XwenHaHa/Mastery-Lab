# Python 进阶：并发与异步

本教材用于验证 Markdown 解析：一级标题作课程名，二级标题作章节，三到六级标题作知识点，代码围栏按语言与行数统计。

## 第 1 章 进程、线程与协程

本章从「为什么要并发」讲起，先给出可运行的最小例子，再逐步逼近事件循环的细节。

### 1.1 为什么需要并发

把 **等待** 拆出来看：磁盘 IO、网络 IO、用户输入，绝大部分时间 CPU 都在空转。`time.sleep` 就是最小可观察的等待。

```python
import time

def fetch(name: str) -> str:
    # 模拟一次 200ms 的网络请求
    time.sleep(0.2)
    return f"{name} done"
```

#### 1.1.1 GIL 的边界

GIL 让同一时刻只有一个线程执行 Python 字节码，所以 CPU 密集任务不能靠多线程提速。先确认解释器版本：

```bash
python -c "import sys; print(sys.version)"
```

##### 1.1.1.1 何时绕过 GIL

IO 密集任务在等待时会释放 GIL，因此线程依然有效；纯计算任务应当换进程，或者换成能释放 GIL 的扩展库。

###### 1.1.1.1.1 实验设计

固定同一份任务列表，分别用串行、线程池、进程池跑一遍，记录墙钟时间，比较三次结果。

### 1.2 事件循环

事件循环本质是一个「任务队列 + 就绪回调」的循环体。协程被调度时才会真正执行，没有 await 的地方永远不会切换。

```json
{"loop": "asyncio", "mode": "single-thread", "awaitable": true}
```

## 第 2 章 实战：并发下载

用一个真实的 HTTPS 请求把前面三节串起来：先写串行版本拿到基线，再换成 asyncio 版本对照。

### 2.1 串行版本

基线版本用标准库 `urllib`，一行一个请求，最容易读，也最慢。

```python
from urllib.request import urlopen

URLS = ["https://example.com", "https://example.org", "https://example.net"]

for url in URLS:
    with urlopen(url, timeout=5) as resp:
        print(url, resp.status)
```

### 2.2 异步版本

同样三个请求，用 `asyncio.gather` 并发发出，墙钟时间接近单个请求的耗时。

```python
import asyncio
import httpx

async def head(client: httpx.AsyncClient, url: str) -> int:
    resp = await client.head(url)
    return resp.status_code

async def main() -> None:
    async with httpx.AsyncClient(timeout=5) as client:
        results = await asyncio.gather(*(head(client, u) for u in URLS))
        print(results)

asyncio.run(main())
```

## 第 3 章 练习

三层练习：先复述概念，再补全代码，最后独立实现。每完成一层把结论写进学习笔记。
