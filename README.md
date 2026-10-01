# 智慧农业多语言一体机服务系统

> 面向少数民族地区农业自助终端的多语言一体机 —— 拍照识病、AI 农事问答、历史记录、数据看板，配套 Web 管理后台。

## 一句话简介

农村老人和少数民族农户用手机 App 有门槛：看不懂、不会用、信号差。本项目把服务做成**村口的一台大屏自助机**：6 种语言自由切换、字号放大到 3 米外看得清、拍照放上病叶就能出防治方案、随时能一键呼叫工作人员。后台则给农技员用，负责用户、大模型配置、词条维护和运营看板。

## 界面预览

### 登录页

6 种语言可在此就地切换；登录 / 注册 / 游客三种入口并列，姓名 + 手机号是唯一身份凭据。

![登录页：乡村背景、毛玻璃卡片、语言下拉与登录注册双页签](docs/image/登录界面.png)

### 一体机主界面 · 多语言

四个功能入口铺满整屏。六种语言共用同一套布局 —— 只切文案，不做 RTL 镜像。

![一体机主界面：四个功能入口与各自的农业插画](docs/image/主页.png)

| 维吾尔语 | 哈萨克语 |
|---|---|
| ![维吾尔语主界面](docs/image/维语主页界面.png) | ![哈萨克语主界面](docs/image/哈萨克语主页界面.png) |

| 藏语 | 传统蒙古文 |
|---|---|
| ![藏语主界面](docs/image/藏语.png) | ![传统蒙古文主界面](docs/image/蒙古语.png) |

### 拍照识病

左侧取景（本地上传，或扫码用手机拍照后回传），右侧直接出报告；病斑位置在照片上框出，标注本地语言病名与置信度。

![拍照识病：左侧取景右侧报告，照片上绘制检测框](docs/image/拍照检测界面.png)

### AI 农事问答

![农事问答：对话流与快捷提问入口](docs/image/农事顾问.png)

### 历史记录与打印单

| 历史记录 | 打印单 |
|---|---|
| ![历史记录：按检测/问答分页，条目可展开详情](docs/image/历史记录.png) | ![打印单：带上上传的照片与检测框](docs/image/打印界面.png) |

### 数据看板

只统计当前用户自己的数据：累计检测、累计问答、最常见问题、类型分布与近 7 天趋势。

![数据看板：KPI、类型分布环形图与 7 天趋势柱状图](docs/image/数据看板.png)

## 技术栈

| 层 | 技术 |
|---|---|
| 终端端（一体机大屏） | Vue 3 + Vite + Pinia + Vue Router，**自研适老化样式，不引入 UI 组件库** |
| 管理后台 | Vue 3 + Vite + Element Plus |
| 后端 | Python FastAPI + SQLAlchemy 2.0（异步）+ SQLite + JWT |
| 识别 | YOLOv8 ONNX 双模型（本地 CPU 离线）+ 智谱 GLM-4.6V 图片理解 + 启发式兜底 |
| 问答 | 多厂商大模型（OpenAI 兼容协议）+ 本地知识库降级 |
| 知识库 | JSON 静态库（16 个类别 / 4 类营养元素 / 4 种作物农事日历） |

## 快速开始

双击根目录的 **`start.bat`** 即可。它会自动检查 Python / Node、释放被占用的端口、按需安装依赖、生成 `.env`、等后端就绪后再拉起前端。

| 入口 | 地址 |
|---|---|
| 终端端（一体机大屏） | http://localhost:5189/ |
| 管理后台 | http://localhost:5189/admin.html |
| 后端接口文档 | http://127.0.0.1:8002/docs |

**演示账号**：管理后台 `admin / admin123`；终端端填个姓名就能进，也可以点「游客模式」。

> 端口 5189 / 8002 是刻意选的：5173、5188、8001 常被本机其它项目占用，避开以免互相抢占。

手动启动：

```bash
# 后端
cd backend
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn app.main:app --host 0.0.0.0 --port 8002

# 前端
cd frontend
npm install
npm run dev          # http://localhost:5189
```

## 项目结构

```
SmartAgricultureKiosk/
├── start.bat                    一键启动（含依赖检查与端口释放）
├── backend/
│   ├── app/
│   │   ├── main.py              入口：中间件 + 异常处理 + 路由挂载 + 启动播种
│   │   ├── config.py            配置中心（读 .env，含多厂商密钥）
│   │   ├── constants.py         6 语言、角色、严重度、作物、抑制上传限制
│   │   ├── schemas.py           全部请求/响应模型
│   │   ├── api/                 system / auth / recognize / mobile / chat / history / stats / admin
│   │   ├── core/
│   │   │   ├── detector.py      YOLOv8 ONNX 双模型推理（叶部病害 55 类 / 农田昆虫 21 类）
│   │   │   ├── vision.py        识别链编排（域检查 → 双模型 → 图片理解 → 启发式兜底）
│   │   │   ├── knowledge.py     知识库加载、多语言兜底、关键词检索
│   │   │   ├── llm.py           多厂商大模型适配 + 无密钥降级
│   │   │   ├── records.py       识别记录的多语言快照与还原
│   │   │   ├── security.py      pbkdf2 口令哈希 + JWT
│   │   │   ├── auth.py          认证依赖与角色校验
│   │   │   ├── middleware.py    请求日志 + 滑动窗口限流
│   │   │   └── exceptions.py    统一异常处理
│   │   └── db/                  database.py（异步引擎）+ models.py（6 张表）
│   ├── knowledge/               pest_disease.json / fertilizer.json / crop_calendar.json
│   ├── static/samples/          "试试看"入口用的真实病叶图（随仓库分发，非占位图）
│   ├── scripts/                 诊断工具：check_detection.py / check_stream.py / decode_qr.py
│   ├── tests/test_smoke.py      端到端冒烟测试（99 项断言）
│   └── uploads/                 用户上传的图片
├── frontend/
│   ├── index.html               终端端入口
│   ├── admin.html               管理后台入口
│   └── src/
│       ├── kiosk/               终端端：views / components / stores / i18n / styles
│       └── admin/               管理后台：views / layouts / stores / styles
└── docs/多语言内容待补清单.md
```

## 核心设计决定

### 1. 识别链：四级降级，能离线的绝不先上云

一体机摆在村口，网络时好时坏，所以识别不押注任何一个单一方案。按顺序往下走，**前一级有可信结果就直接返回**，并把用了哪一级如实写进 `engine` 字段：

| 级 | 方案 | 依赖 | 说明 |
|---|---|---|---|
| 0 | 域检查门 | 本地 OpenCV | 先判断"像不像农作物"，挡掉截图/饭菜/人脸被判出高置信度 |
| 1 | 叶部病害模型（YOLOv8n，55 类） | 本地 ONNX，12MB | 离线、纯 CPU、毫秒级 |
| 2 | 农田昆虫模型（YOLOv8m，21 类） | 本地 ONNX，89MB | 只在病害模型无检出时才加载执行 |
| 3 | 整图分类器（MobileNetV2，PlantVillage 38 类） | 本地 ONNX，9MB | 离线；**门槛设得很高，当前几乎不采信**，原因见下 |
| 4 | 图片理解（智谱 GLM-4.6V-Flash，免费） | 联网 | 本地都看不清时才交给云端，2~4 秒 |
| 5 | 启发式颜色纹理分析 | 本地纯 Python | 断网、缺模型、无密钥时的最后兜底 |

> **第 3 级的门槛为什么定得这么高**：现用的分类器权重训练自 PlantVillage —— 那是**实验室受控拍摄**的数据集（纯色背景、单叶居中）。拿本项目 4 张真实照片实测，它的 top1 全部落在 0.16~0.52，且有明确判错（蚜虫图被判成苹果锈病、玉米图被判成番茄晚疫病）。所以采信条件设为「top1 ≥ 0.70 **且** top1 至少是 top2 的 1.8 倍」，宁可不采信也不能让它拿错病名去覆盖后面更可靠的图片理解。想要它真正发挥作用，需要换成田间数据训练的权重（换掉 `data/models/plant_classifier.onnx` 即可，映射表在 `core/classifier.py`）。

**模型只负责"看到什么、在哪里"，症状 / 防治 / 用药一律来自本地知识库** —— 那部分经过校对，而且天生带 6 语言。图片理解返回的中文病名也会先回知识库检索：命中就用知识库内容；没命中才退回它自己的描述、标记为参考方案，同时**丢弃它给的用药信息**（未经校验的药剂和稀释倍数不能直接当处方开给农户）。

关于检测框：只有第 1、2 级（真做了定位的模型）才会产出框。图片理解不画框 —— 它没有定位能力，早期为了"看起来有框"塞过一个盖满整幅图的框，那是误导，农户会以为整片叶子都是病灶。

两个 ONNX 权重合计约 100MB，**不进版本库**（见 `.gitignore` 里的 `backend/data/`）。放到 `backend/data/models/` 即可；文件缺失时自动跳过对应级别，服务照常启动。服务启动时会在后台把模型预热好，避免第一位农户对着"识别中"干等。

### 2. 背景剔除（一个实测踩到的坑）

一体机明确引导用户「把病叶平放在白纸上拍照」。第一版没剔背景，结果**每一张白底照片都被判成白粉病**（白纸把 `whitish_ratio` 顶到 85%+）。现在先用最外一圈像素估背景色（中位色），背景成片出现时（边缘占比 > 60% 且全图占比 > 25%）才剔除，再在前景上算比值。`tests/test_smoke.py` 里有对应的回归断言。

### 3. 大模型：填哪家用哪家，不填也能用

`.env` 里列好了智谱 / 通义 / DeepSeek / Kimi / 文心 / 自定义六家的密钥槽位，把 `AI_PROVIDER` 填成对应名字、再填 key 即可。除文心外都是 OpenAI 兼容协议，只写一套调用；文心单独走 AK/SK 换 access_token 的分支。

**没填 key 或调用失败都不会报错给用户**：自动降级到本地知识库检索（关键词匹配知识库后拼装回答），并在响应里如实标记 `source="local"` 或 `"fallback"`。农村弱网下这比弹错误框有用。

问答走**流式**（`POST /api/chat/stream`，SSE）：首字实测 0.4 秒左右到达，前端逐字渲染，而不是等整段生成完再一次性蹦出来 —— 对站在机器前的老人，这两种体感的差别比"快一秒慢一秒"大得多。GLM-4.5/4.6 系列会显式关闭思考模式（实测 14.8s → 8.8s，质量不降）。

### 4. 多语言：UI 全量，专业内容部分待补

- **界面文案**：6 种语言（简体中文 / 英语 / 维吾尔语 / 哈萨克语 / 藏语 / 传统蒙古文）**全部齐备**，包括步骤条、按钮、提示、错误信息、快捷提问。
- **专业知识内容**（症状、病因、防治、用药）：目前**中文与英文完整**，另外 4 种语言缺失时自动回退中文，**不会出现空白**。原因是这类文本需要母语者 + 农技员交叉校对，不能靠机器直译糊弄。需要补哪些、补成什么格式，见 [docs/多语言内容待补清单.md](docs/多语言内容待补清单.md)。
- 切换语言时**不做 RTL 镜像布局**（维吾尔/哈萨克语仍从左到右排版），这是产品方的明确要求。
- 字体回退链已配好：维/哈 → Microsoft Uighur，藏 → Microsoft Himalaya，蒙 → Mongolian Baiti。

### 5. 整屏固定 + 适老化

- `html/body` 锁死高度不滚动，只有历史列表、报告区、看板内部滚动。
- 间距三档令牌：小元素 ≤12px（`--k-pad`）、卡片与容器 16px（`--k-pad-md`）/ 20px（`--k-pad-lg`）。
- 根字号 `clamp(16px, 1.15vw, 23px)`，1920 屏约 22px，卡片标题约 50px。
- 触控目标 ≥ 64px；`:focus-visible` 描边；尊重 `prefers-reduced-motion`。

## 接口一览

| 分组 | 主要接口 |
|---|---|
| 系统 | `GET /api/system/health` `/info` `/langs` `/classes` `/calendar` |
| 认证 | `POST /api/auth/login` `/guest` `/kiosk/register` `/kiosk/login`；`GET /api/auth/me` |
| 识别 | `POST /api/recognize`（multipart）；`GET /api/recognize/samples` |
| 扫码上传 | `POST /api/recognize/mobile/session` `/upload`；`GET /api/recognize/mobile/pending`；手机上传页 `GET /m` |
| 问答 | `POST /api/chat/ask`（一次返回）、`POST /api/chat/stream`（SSE 逐字）；`GET /api/chat/quicks` |
| 历史 | `GET /api/history` `/chats` `/{record_no}`；`DELETE /api/history/{record_no}` |
| 看板 | `GET /api/stats/mine`（终端端只给本人）；`GET /api/stats/overview` `/trend` `/disease-dist` `/regions` `/top-questions`（后台） |
| 后台 | `GET /api/admin/dashboard` `/users` `/providers` `/lang-resources` `/logs`（增删改） |

完整交互式文档见 http://127.0.0.1:8002/docs 。

**权限模型**：终端端接口允许匿名/游客访问（历史记录按 `user_id` 隔离，未登录只看自己的）；`/api/admin/*` 全部要求 `role ∈ {admin, operator}`。厂商密钥出参一律掩码，绝不返回完整 key。

## 测试

```bash
cd backend
python tests/test_smoke.py      # 或 pytest tests/test_smoke.py -q
```

99 项断言，覆盖系统信息、认证与越权、真实图片识别的整条链路、多语言取值与回退、历史记录、看板聚合、后台增删改与操作留痕。**不需要后端先启动**（用 TestClient 直连应用）。

> 注意：冒烟测试会注册固定手机号、并依赖空库，**请先在干净数据库上跑**（`backend/data/kiosk.db` 有数据时会因"手机号已注册"等连锁失败）。

```bash
cd frontend
npm run build                   # 双入口构建
```

## 已知边界（如实披露）

1. **识别链的能力边界**：本地两个模型覆盖 55 类叶部病害 + 21 类农田昆虫，但**映射到本知识库的只有 13 个条目**——认得出但知识库没有对应方案的，只报大类不给具体名（不硬套病名去开药）。本地都判不出时交给图片理解，它的结论会标记为「参考方案，请以农技员意见为准」。都不能替代专业植保诊断。
2. **知识库覆盖 16 个类别**，是演示规模的精选集，不是完整植保手册。扩类别只需往 `knowledge/pest_disease.json` 加条目，前后端都会自动生效。
3. **少数民族语言的专业内容待补**（见上文 4）。
4. **限流是进程内实现**（内存字典），适合单实例。多实例部署要换成 Redis。
5. **数据库用 `create_all` 建表**，没有迁移机制。上生产应引入 Alembic。
6. **管理后台完整引入 Element Plus**（gzip 约 297KB）。后台是独立 chunk，不影响终端端首屏；如需优化可改为按需引入。
7. **语音播报依赖浏览器 `speechSynthesis`**。维吾尔/哈萨克/藏/蒙的语音包在多数系统上不存在，会退回中文朗读；`speechSynthesis` 不可用时提示用户。
