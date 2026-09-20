# rules 目录说明

这个目录存放 Agent 成长过程中积累的规则与偏好。

除了本 README 之外，目录里的所有 `.md` 文件都会在 Agent 做决策时
注入到 prompt 中，Agent 必须遵守。

## 文件来源

- `feedback.md`：通过手机端 / CLI 的"记录反馈"功能自动追加的用户纠正
- 也可以手工新建规则文件，例如 `ehall-rules.md`：

  ```
  # EHALL 规则

  - 报修时间格式统一为 yyyy-MM-dd HH:mm
  - 提交前必须向用户展示全部关键字段
  ```

## 管理

- 规则文件是人类可读、可编辑的 Markdown
- 用 git 管理变化：
  `git add rules && git commit -m "更新规则"`
- 规则太多时可以把 feedback.md 拆分成多个主题文件
