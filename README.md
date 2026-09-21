# Personal Assistant — 会成长的个人助手

课程实验项目：一个真正可用的个人助手。能够持续读取 smail 邮件、
处理任务、准备 EHALL 事务，并可以通过手机操作；用户纠正与偏好
会沉淀为可读可编辑的规则，让 Agent 持续成长。

## 功能

- **个人资料库**：Markdown 资料检索；AI 只能使用资料库中真实存在的信息
- **持续读取 smail**：IMAP 拉取、邮件去重（Message-ID + 备用 ID + 处理收据）、
  AI 分析、需要行动的邮件自动创建任务；邮件控制台支持状态过滤、
  标记"已做完"、重建任务
- **Agent 任务处理**：任务状态机、缺少信息时向用户询问、
  用户补充后继续处理、程序重启后任务不丢失；
  提醒类请求（"提醒我明天交作业"）也能识别并创建任务
- **EHALL 宿舍报修**：通过 HAR 流量分析逆向出真实接口（提交、
  报修类型 47 项 / 区域 138 项的字典树），AI 从真实选项中选择、
  提交前字典码校验，默认模拟提交（`EHALL_DRY_RUN=0` 真实提交）
- **高风险人工确认**：提交表单等操作必须先展示确认单（关键字段 + 后果），
  用户明确确认后才进入 EXECUTING，Agent 不能自行确认
- **手机端**：Flask Web 页面发起任务、查看进度、补充信息、
  查看确认单、确认/取消
- **邮件与任务双向同步**：任务完成 → 邮件自动"已完成"；
  任务重新打开 → 邮件回到"待办"；标记邮件"已做完" → 任务同步完成
- **成长机制**：用户纠正 / 偏好保存为 rules/ 下的规则文件，注入后续决策

## 项目结构

```
personal-assistant/
├── main.py                    # CLI 入口（python main.py）
├── server.py                  # Web 入口（手机端，Flask API + 页面）
├── config.py                  # 全局配置（所有路径锚定项目根目录）
├── agent/                     # Agent 核心
│   ├── llm.py                 # DeepSeek 调用（JSON 解析 + 重试）
│   ├── email_agent.py         # 邮件分析
│   ├── user_agent.py          # 用户请求分析（与邮件分析同构）
│   ├── task_manager.py        # 任务存储（加锁、原子写、ID 持久计数器）
│   ├── task_processor.py      # 任务处理核心（无 UI，返回事件流）
│   └── growth.py              # 成长规则：记录反馈 / 注入规则
├── services/                  # 服务层（CLI 与 Web 共用的业务入口）
│   ├── email_service.py       # 邮件：拉取→查重→分析→建任务
│   └── agent_service.py       # Agent：处理/继续/确认/取消
├── entrypoints/
│   ├── cli.py                 # 命令行交互（主菜单/邮件控制台/报修中心/任务中心）
│   ├── scheduler.py           # 后台调度：定时邮件 + 自动处理 NEW + 启动恢复
│   └── terminal.py            # 终端样式：ANSI 柔和配色 + emoji（非终端自动纯文本）
├── tools/
│   ├── email.py               # smail IMAP 读取与解析
│   ├── personal_db.py         # jieba 资料库检索
│   └── ehall.py               # 报修表单构造 + 字典树抓取 + 真实提交（dry-run 开关）
├── web/index.html             # 手机端页面
├── rules/                     # 成长规则（可读可编辑，git 管理）
├── data/
│   ├── documents/             # 个人资料库（profile.md、preferences.md）
│   ├── emails/processed.json  # 邮件处理收据（去重 + 完成标记）
│   └── ehall_codes.json       # EHALL 字典码缓存（类型 47 项 / 区域 138 项）
├── tasks/tasks.json           # 任务数据
└── tests/                     # 单元测试（unittest，全部离线可跑）
```

```
Email 入口                          用户入口（CLI / 手机）
smail 读取                          输入请求
    │                                  │
    └──────────► 任务系统 ◄─────────────┘
                    │
                Agent 核心
                    │
       ┌────────────┼────────────┐
    资料库        EHALL        其他工具
                    │
              高风险确认单
                    │
               EXECUTING
```

## 安装

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# 配置 .env（不要提交到 git）
DEEPSEEK_API_KEY=...
SMAIL_EMAIL=xxx@smail.nju.edu.cn
SMAIL_PASSWORD=...       # 企业邮箱客户端专用密码
EHALL_COOKIE=...         # 浏览器登录 ehall.nju.edu.cn 后粘贴 Cookie（可选）
EHALL_DRY_RUN=1          # 1 模拟提交（默认），0 真实提交
```

## 使用

### 命令行

```bash
.venv/bin/python main.py                    # 主菜单：选 1 邮件 / 2 报修 / 3 任务中心
```

CLI 带 emoji 与柔和配色（淡蓝/黄/淡粉/红/淡绿）；管道输出或
重定向时自动纯文本，`NO_COLOR=1 python main.py` 可强制关闭颜色。

主菜单：

```
1. 邮件服务：检查 smail，AI 分析并自动创建任务
2. 宿舍报修：发起报修 / 查看报修记录
3. 任务中心：待办任务 / 全部任务
4. 数据管理：清空任务数据 / 清空邮件记录
q. 退出
```

任务中心（菜单 3）：

```
1. 待处理任务（需要你补充/确认的）
2. 全部任务（含已完成/失败/取消，可看执行结果）
q. 返回
```

宿舍报修中心（菜单 2）：

```
1. 发起新的报修
2. 查看报修记录（过往报修及状态），输入任务 ID 可继续处理
q. 返回
```

邮件与任务双向同步：任务完成/取消 → 对应邮件自动显示"已完成"；
任务重新打开 → 邮件回到"待办"；标记邮件"已做完" → 对应任务同步完成。

邮件服务里每封邮件带状态（待办 / 已完成 / 通知类 / 未分析），按键操作：

```
1 只看待办（已分析、需要行动、还没做）
2 只看已完成（标记过做完了）
3 只看未处理（未分析 + 待办）
a 显示全部
d 序号  把这封标记为"已做完"（对应的进行中任务会同步完成）
u 序号  取消"已做完"标记
t 序号  重建任务：任务被清空/已结束时重新创建或重新打开，并自动处理
q 返回菜单
```

数据管理（都需要输入 y 确认）：

```
1. 清空任务数据：tasks.json 清空，任务 ID 从 1 重新开始
   （邮件记录不动，已处理过的邮件不会重新分析）
2. 清空邮件记录：processed.json 删除，邮件会重新分析并重建任务
   （任务数据不动）
3. 更新 EHALL 字典码：抓取报修类型/区域选项，缓存到
   data/ehall_codes.json（需先配置 EHALL_COOKIE）
```

也可以跳过菜单直接运行某个功能：

```bash
.venv/bin/python main.py email              # 直接运行邮件服务
.venv/bin/python main.py tasks              # 列出任务
.venv/bin/python main.py new 我要报修宿舍水龙头
.venv/bin/python main.py feedback 报修时间格式要统一 [--commit]
```

### 后台调度（持续运行）

```bash
.venv/bin/python entrypoints/scheduler.py --once        # 只跑一轮
.venv/bin/python entrypoints/scheduler.py               # 持续运行
PA_POLL_INTERVAL=60 .venv/bin/python entrypoints/scheduler.py
```

### 手机端 Web

```bash
.venv/bin/python server.py        # 监听 0.0.0.0:5000，可用 PA_PORT 改端口
PA_SCHEDULER=0 .venv/bin/python server.py   # 不启动后台邮件调度（测试时用）
```

手机浏览器访问 `http://<电脑IP>:5000`（与电脑同一局域网）。

WSL2 需要做一次端口转发（Windows 管理员 PowerShell）：

```powershell
netsh interface portproxy add v4tov4 listenport=5000 listenaddress=0.0.0.0 `
    connectport=5000 connectaddress=(wsl hostname -I)
```

REST API（CLI 与手机共用同一批服务函数）：

```
GET  /api/tasks                  任务列表
POST /api/tasks                  {text} 创建任务并自动处理
GET  /api/tasks/<id>             任务详情（history/确认单/报修数据）
POST /api/tasks/<id>/input       {text} 补充信息
POST /api/tasks/<id>/confirm     用户确认执行（唯一进入 EXECUTING 的入口）
POST /api/tasks/<id>/cancel      取消任务
POST /api/emails/check           手动检查一次邮件
POST /api/feedback               {content} 记录用户纠正/偏好
```

## 任务状态机

```
NEW → PROCESSING → WAITING_USER ──(用户补充)──┐
        │            ▲                        │
        │            └────────────────────────┘
        │  ┌─ 无需行动 → COMPLETED
        └─► WAITING_CONFIRMATION ──(用户确认)──► EXECUTING
              │                    (用户取消)     │
              └──────────► CANCELLED              ├─► COMPLETED（成功）
                                                  └─► FAILED（失败，不再卡死）
```

需要用户亲自行动的任务（交作业、提交材料等）即使不需要个人信息，
也会进入 WAITING_CONFIRMATION 等用户确认"已完成"，Agent 不能替用户完成。

所有状态变迁记录在任务的 history 里；重启后 WAITING_* 状态不丢失，
EXECUTING 中中断的任务由调度器启动恢复（成功→COMPLETED，否则→FAILED）。

## 测试

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

全部测试离线运行（LLM / IMAP 均 mock），不会消耗 API 或触碰真实邮箱。

## 安全

- `.env`（API key、邮箱密码、Cookie）不入 git
- 高风险操作（提交表单、发送邮件、退课、取消申请、删除数据）
  永远先展示确认单，用户明确确认后才执行
- EHALL 真实提交默认关闭（`EHALL_DRY_RUN=1`）：确认后返回
  "模拟提交成功"，不产生真实报修单；设 `EHALL_DRY_RUN=0` 才真实提交

## 成长规则

`rules/` 目录下的 `.md` 文件（除 README.md）会在 Agent 每次决策时注入 prompt。
用户纠正通过 CLI `feedback` 或手机端"记录反馈"写入 `feedback.md`；
也可以手工新建规则文件。规则文件用 git 管理变化。

## EHALL 真实提交

通过分析浏览器流量（HAR）与前端 JS，逆向出宿舍报修应用的
真实接口（应用运行在 ehallapp.nju.edu.cn 的 ssbxapp 上，
金智 EMAP 平台）：

| 用途 | 接口 |
|---|---|
| 表单模型 | `POST /xsfw/sys/ssbxapp/modules/wybx.do` |
| 报修类型树 | `POST /xsfw/code/64bfd69f-….do`（pId 递归，47 个叶子选项） |
| 报修区域树 | `POST /xsfw/code/281e295f-….do`（138 项，精确到楼栋） |
| 提交报修 | `POST /xsfw/sys/ssbxapp/modules/repairApply/repairApplyAdd.do` |

提交请求为表单编码 `data=<JSON字符串>`，成功判定 `code=="0"`。

使用前两步准备：

1. **配置 Cookie**：浏览器登录办事大厅（ehall.nju.edu.cn）并打开
   宿舍报修应用 → F12 复制 Cookie → 粘贴到 .env 的 `EHALL_COOKIE`
2. **更新字典码**：菜单 4 数据管理 → 3 更新 EHALL 字典码，
   程序抓取报修表单选项并缓存到 data/ehall_codes.json

AI 提取报修字段时会把真实选项注入 prompt 逐字选择（例如
"空调坏了"→"水电类/空调无法开启（电源故障）"）。提交前进行字典码
解析，匹配不上或有歧义时明确报错并列出候选，不会提交错误数据。

提交时 `EHALL_DRY_RUN=1`（默认）只模拟；确认没问题后设
`EHALL_DRY_RUN=0` 才会真实提交。真实提交前的人工确认始终保留。

## 设计要点

- **分层架构**：入口层（CLI / Web / 调度器）→ 服务层 → Agent 核心 →
  工具层 → 数据层。业务逻辑不依赖 `input()` / `print()`，
  Agent 返回结构化事件流，CLI 只是渲染器——同一套服务函数
  支撑命令行、手机页面，未来可加微信等新入口
- **双入口同构**：邮件触发与用户主动发起两种任务来源
  共用同一任务模型与分析流程，互不为前置依赖
- **确认单快照**：进入 WAITING_CONFIRMATION 时把关键字段与后果
  一次性写入任务快照，UI 只读快照；Agent 永远无法自行确认
- **邮件去重三层**：Message-ID（缺失时用主题+发件人+时间）→
  处理收据（processed.json）→ 历史任务兜底回溯
- **邮件与任务双向同步**：任务状态变化自动同步对应邮件的完成标记，
  两边视图永远一致
- **字段级合并**：用户补充信息后重新提取表单时，新提取为空的字段
  保留旧值，用户提供过的信息不会因为 AI 丢字段而反复被问
- **真实字典约束**：EHALL 报修类型/区域只能从真实选项中逐字选择，
  提交前代码解析 + 歧义检测，杜绝编造数据
- **持久化与并发安全**：任务存储全局锁 + 原子写（临时文件 +
  os.replace），ID 用持久计数器不复用；重启后等待状态不丢失，
  EXECUTING 中断任务由调度器恢复
- **成长规则注入**：rules/ 下的规则文件注入每次决策 prompt；
  无规则时行为不变

## 开发说明

- 每个阶段的重构都有独立 commit（`git log --oneline` 可查看），
  基线标签为 `refactor-baseline`
- 上传前安全自查：真实密钥只在 .env（git 忽略）；分析流量的
  HAR 文件（*.har）已加入 .gitignore，勿打包进提交物
