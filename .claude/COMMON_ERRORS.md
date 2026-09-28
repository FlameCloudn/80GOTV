# 常见错误速查

开发中常遇到的错误和修复方法。

---

## ImportError: No module named 'xxx'

现象:
```
ModuleNotFoundError: No module named 'flask'
ImportError: No module named 'libsql_experimental'
```

原因: 缺少 Python 包，没有安装或用错了 Python 环境

修复方法:
```
pip install flask
pip install libsql_experimental
# 或者一次性安装所有依赖
pip install -r requirements.txt
```

注意：本项目用 `python` 和 `pip`，不是 `python3` 和 `pip3`。

---

## 登录提示"用户名或密码错误"太频繁

现象: 用户短时间内输错几次密码后就一直弹"用户名或密码错误"

原因: 没有登录限速机制，或者限速太严格把正常用户锁了

修复方法:
- 检查 `routes/auth.py` 里的登录限速逻辑
- 调整允许失败次数（当前默认 3 次/分钟 比较宽松）
- 如果数据库 locked 导致登录检查失败，也会误判，检查是否有长时间未提交的事务

---

## 数据库 locked

现象:
```
sqlite3.OperationalError: database is locked
```

原因: 有另一个进程或线程在写数据库，SQLite 只允许一个写入者同时存在

修复方法:
1. 关掉所有正在运行的程序（包括其他终端窗口里的 app.py）
2. 如果有后台进程，用任务管理器关掉 python.exe
3. 重新启动 `python app.py`
4. 如果频繁出现，考虑检查代码里是否有 `conn.close()` 遗漏
