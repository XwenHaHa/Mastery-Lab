# P1.3 教学验收 · Python 入门

## 第一章 基础表达

### 变量与赋值

变量让程序为数据命名。教材例子：星河书店把一本书的单价命名为 price。

```python
price = 37
quantity = 2
total = price * quantity
print(total)
```

预期输出 74。等号是赋值，不是数学方程。先赋值再使用变量。变量名不能以数字开头。

### 列表与索引

列表按顺序保存多个值。星河书店的书架使用 books 保存三本书。

```python
books = ["Python", "数据库", "网络"]
print(books[0])
```

预期输出 Python。索引从 0 开始。超出范围会产生 IndexError。

### 条件判断

根据库存决定是否可以借书。if 后面写条件，分支内部必须缩进。

```python
stock = 3
if stock > 0:
    print("可以借书")
else:
    print("暂无库存")
```

预期输出 可以借书。冒号与缩进不能省略。
