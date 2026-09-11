# 开发规范（对本项目的所有 AI code agent 生效）

> **两层用法**：
> - **全局层**：跨项目通用红线（说中文说人话 / 不确定就问不许猜 / 不夹带私货 / 改前先问）放在 `~/.zcode/AGENTS.md`（Windows 与 WSL 的 ZCode 各读各自 home 下的一份），每次会话自动注入，对所有项目生效——**不要在项目里重复写这四条**。
> - **项目层**：本文件即项目层规范。ZCode 先注入全局层、再注入本文件；项目层可以收窄或加严，**不得放宽全局红线**。

---

## 本项目信息

- 项目名：Agent_feishu
- 一句话现状：飞书简历助手（GitHub 主仓 KDHR9100/Agent_feishu，本地为最全副本）；**项目已有 `CHANGELOG.md`（大写），它就是本模板所指的 ChangeLog，不要另建文件。**

## 一、项目红线（通用红线 1~4 见全局 ~/.zcode/AGENTS.md，此处不重复）

1. **每次改动都要记账。** 本项目维护专门的 ChangeLog，每一次改动都必须在其中记录。
2. **做完要回写 BRD。** 每次开发结束后，都需要在 BRD.md 中做出对应的更新与记录，防止文档和实物越走越远。

## 二、需求拷问：/grill-me（写 requirement 之前必跑）

- **是什么**：Matt Pocock 的 `/grill-me` 技能，装在用户级 `~/.agents/skills/grill-me/`，所有项目、ZCode/Claude 通用。
- **干什么**：把 agent 变成一个不留情面的面试官——分轮提问（一轮约 10~15 个针对性问题），等你答完再问下一轮，直到设计树的每个分支都被问清；最后跟你确认一份简短 spec，确认后才动工。
- **什么时候必须用**：任何新需求进入开发流程、准备生成 `requirement.md` 之前，必须先跑 `/grill-me`；拷问产出的确认 spec 就是 requirement.md 的底稿。
- **怎么用**：对话里输入 `/grill-me`，描述你要做的东西，然后逐轮回答问题。

## 三、目录与命名规范

- 项目根目录用英文命名，形如 `xxx_dev`。
- 模块文件夹一律 `Module-XXX`，**必须英文命名，不允许中文**；必须存在 `Module-Common`，专门放置共通部分与前置部分。
- 根目录维护全局文档：`BRD.md`、`module-list.md`、`task-all-list.md`、`ChangeLog`。
- 每个模块内部维护自己的一套：`requirement.md`、`design.md`、`task.md`，互不干扰。
- `Backup/` 文件夹用于定档备份：模块 task.md 确认后、需求变更前，都要先把旧版备份进去（命名带日期）。
- **Skill 存放红线**：
  - **项目专属 skill**：正本一律放本项目 `Skill/` 文件夹，不允许散落在别处。注意 ZCode 不会自动加载项目根的 `Skill/`——要让它真正生效，需在项目 `.zcode/skills/` 下放副本或链接。（本项目已有的 `app/skills/` 是应用代码的一部分，不属于本条管辖。）
  - **跨项目通用 skill**：一律装用户级 `~/.agents/skills/`，ZCode、Claude 等工具会自动发现（如 `/grill-me`）。

## 四、文档链与状态约定

- 上游顺序固定：`BRD.md` → `module-list.md` → 各模块 `requirement.md` → `design.md` → `task.md` → `task-all-list.md`。
  **BRD.md 永远是最上游的唯一依据，任何改动都要回写到它。**
- 生成顺序有门槛：新需求先用 `/grill-me` 拷问定稿（见「二、需求拷问」），spec 确认后才生成 requirement.md；确认完 requirement 才准生成 design；确认完 design 才准生成 task。
- 模块编号形如 `TG-xxx`，记录在 module-list.md。开发状态只有四种：`未开发 / 开发中 / 测试未通过 / 已完成`。
  **只有该模块的集成测试通过，才能标记为「已完成」**（单个任务测试通过不算）。
- 汇总 task-all-list.md 时，**任务编号必须与各模块 task.md 保持一致，不允许擅自拆分或合并任务**；
  每个任务要有序号、Task ID、所属 Module、内容简介、前置依赖、可并行、开发状态。

## 五、开发守则（执行任务时）

- 按 Task ID 逐个执行，先在 module-list.md 中把该模块状态改为「开发中」。
- 以最新代码的实际结构为准，**避免硬编码与使用占位符**。
- 做完就测；可能有多个任务并行开发，因此只保证自己这部分测试通过，**不能影响其他既有功能**。
- 每次开发都要记录进对应的 task.md，并同步 ChangeLog。
- 模块全部任务完成后：先比对 task-all-list.md 与该模块 task.md 是否一致，再构建集成测试跑通整体链路并记录结果，通过后才在 module-list.md 标记「已完成」。

## 六、需求变更守则

- 需求一变，回到上游重走：先备份（BRD 存成 `BRD_backup_日期`，各模块文档同形式备份），
  再基于 BRD 逐级更新 requirement / design / task / task-all-list，然后才允许动代码。
- 变更开发完成后，对涉及的所有模块做集合测试，确保修正不影响整体运行。

## 七、汇报方式

- 每步产出文档（BRD、requirement、design、task 等）后，停下来等我确认，**没确认不准往下走**。
- 我说"与我预期不符"时：重新查看上一级文档，基于我的反馈修改当前文档，并同步回上一级文档。
- 提到其他任务时必须给 Task ID，不许只写模糊描述。
