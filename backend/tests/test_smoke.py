"""端到端冒烟测试：不依赖外部服务，用 TestClient 跑完整链路。

覆盖：健康检查 → 系统信息 → 登录/游客 → 拍照识别（真实走启发式视觉分析）
      → 农事问答（无大模型时降级本地知识库）→ 历史记录 → 统计看板 → 后台管理。

直接运行：python tests/test_smoke.py
或用 pytest：pytest tests/test_smoke.py -q
"""

from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app, startup  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASSED.append(name)
        print(f"  [PASS] {name}")
    else:
        FAILED.append(f"{name} :: {detail}")
        print(f"  [FAIL] {name} -> {detail}")


def make_leaf_image(style: str = "necrotic") -> bytes:
    """合成一张"叶片"图，避免测试依赖外部图片文件。

    necrotic：绿底 + 褐色斑点（模拟病斑）
    healthy ：纯绿叶（模拟健康叶）
    """
    from PIL import Image, ImageDraw

    size = 420
    img = Image.new("RGB", (size, size), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # 叶片本体：一大块绿色椭圆
    draw.ellipse((30, 30, size - 30, size - 30), fill=(64, 128, 58))

    if style == "necrotic":
        # 褐色同心斑点，制造高 necrosis_ratio 与 spot_density
        spots = [
            (130, 140, 34), (215, 175, 28), (170, 245, 30),
            (265, 285, 26), (120, 300, 22), (280, 130, 20),
            (200, 90, 18), (95, 210, 16),
        ]
        for cx, cy, r in spots:
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(104, 62, 32))
            draw.ellipse((cx - r // 2, cy - r // 2, cx + r // 2, cy + r // 2), fill=(74, 42, 22))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def main() -> int:
    # 必须显式跑一遍启动流程：TestClient 不套 with 时不触发 lifespan，
    # 否则在全新环境（没有 kiosk.db）下会直接报 "no such table: users"。
    asyncio.run(startup())
    client = TestClient(app)

    print("\n=== 1. 系统接口 ===")
    r = client.get("/api/system/health")
    check("GET /api/system/health", r.status_code == 200, r.text[:200])
    check("健康检查返回数据库正常", r.json().get("database") == "ok", r.text[:200])

    r = client.get("/api/system/info")
    info = r.json() if r.status_code == 200 else {}
    check("GET /api/system/info", r.status_code == 200, r.text[:200])
    check("知识库已加载（类别数 > 0）", (info.get("knowledge") or {}).get("class_total", 0) > 0, str(info.get("knowledge"))[:200])
    check("返回 6 种语言", len(info.get("langs") or []) == 6, str(len(info.get("langs") or [])))

    r = client.get("/api/system/classes", params={"lang": "zh-CN"})
    classes = r.json() if r.status_code == 200 else []
    check("GET /api/system/classes", r.status_code == 200 and len(classes) > 0, r.text[:200])
    check("类别不含内部指纹字段", all("signature" not in c and "weights" not in c for c in classes), "signature/weights 泄漏")

    r = client.get("/api/system/calendar", params={"lang": "zh-CN"})
    check("GET /api/system/calendar", r.status_code == 200, r.text[:200])

    print("\n=== 2. 登录与权限 ===")
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    admin_token = (r.json() or {}).get("access_token", "") if r.status_code == 200 else ""
    check("管理员登录", r.status_code == 200 and bool(admin_token), r.text[:200])

    r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong-password"})
    check("错误密码被拒绝", r.status_code == 401, f"实际 {r.status_code}")

    r = client.post("/api/auth/guest", json={"display_name": "测试农户", "lang": "zh-CN"})
    anon_token = (r.json() or {}).get("access_token", "") if r.status_code == 200 else ""
    check("游客进入", r.status_code == 200 and bool(anon_token), r.text[:200])

    r = client.get("/api/admin/users")
    check("无 token 访问后台被拒绝", r.status_code == 401, f"实际 {r.status_code}")

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    anon_headers = {"Authorization": f"Bearer {anon_token}"}

    r = client.get("/api/admin/users", headers=admin_headers)
    check("管理员可访问后台用户列表", r.status_code == 200, r.text[:200])
    r = client.get("/api/admin/users", headers=anon_headers)
    check("非管理员访问后台被拒绝（403）", r.status_code == 403, f"实际 {r.status_code}")

    # 第 3~6 节验的是"数据能正常入库"，必须用正式农户账号：
    # 游客按策略不落库（见第 8 节），拿游客令牌这些断言会全部落空。
    # 农户账号统一走一体机注册接口（手机号是账号主键），不再由后台代建。
    r = client.post(
        "/api/auth/kiosk/register",
        json={"display_name": "冒烟农户", "phone": "13900000001", "lang": "zh-CN"},
    )
    farmer_token = (r.json() or {}).get("access_token", "") if r.status_code == 200 else ""
    check("农户经一体机注册后可拿到登录态", bool(farmer_token), r.text[:200])
    auth_headers = {"Authorization": f"Bearer {farmer_token}"}

    print("\n=== 3. 拍照识别（真实启发式分析）===")
    r = client.post(
        "/api/recognize",
        files={"file": ("leaf.jpg", make_leaf_image("necrotic"), "image/jpeg")},
        data={"lang": "zh-CN", "crop": "", "channel": "local"},
        headers=auth_headers,
    )
    check("POST /api/recognize", r.status_code == 200, r.text[:300])
    rec = r.json() if r.status_code == 200 else {}
    check("返回记录号", bool(rec.get("record_no")), str(rec)[:200])
    check("识别出具体类别或大类", rec.get("category") in {"disease", "pest", "nutrient", "phyto"}, f"category={rec.get('category')}")
    check("置信度在 0~100", 0 <= float(rec.get("confidence") or 0) <= 100, str(rec.get("confidence")))
    check("给出了防治建议", bool(rec.get("treatment")), str(rec.get("treatment"))[:200])
    check("带可解释的诊断依据", isinstance(rec.get("reason", {}).get("features"), dict), str(rec.get("reason"))[:200])
    # 识别链只剩 图片理解 / 启发式 两级（本地 YOLO 已移除），
    # 只要 engine 如实标了来源即可 —— 断言应该约束"字段有效"，而不是"实现细节"。
    check(
        "标注了识别引擎",
        rec.get("engine") in {"glm-4v", "heuristic"},
        str(rec.get("engine")),
    )
    print(f"    识别结果：{rec.get('name')} / {rec.get('category')} / 置信度 {rec.get('confidence')}%")

    # 回归断言：白纸背景不能把结果带偏成白粉病
    # （曾出现过"绿叶+褐斑+白底 → 黄瓜白粉病 85.9%"的误判，根因是白背景被算进 whitish_ratio）
    feats = (rec.get("reason") or {}).get("features") or {}
    check(
        "白纸背景未被误判为白粉病",
        rec.get("class_key") != "cucumber_powdery_mildew",
        f"class_key={rec.get('class_key')}, whitish_ratio={feats.get('whitish_ratio')}, bg_ratio={feats.get('bg_ratio')}",
    )
    check(
        "背景占比已单独统计并剔除",
        "bg_ratio" in feats and feats.get("bg_ratio", 0) > 0.3,
        f"bg_ratio={feats.get('bg_ratio')}",
    )
    check(
        "前景的褐斑被识别为坏死特征",
        feats.get("necrosis_ratio", 0) > 0.03,
        f"necrosis_ratio={feats.get('necrosis_ratio')}",
    )

    # 检测框：合成图上有 6 个明显的褐色斑点，本该圈得出来。
    # 但识别链是分级降级的 —— 落到"图片理解"那一级时**不产出框**：它没有定位能力，
    # 硬塞一个盖满整幅图的框会让农户以为整片叶子都是病灶。
    # 所以这里只约束"给了框就必须合法"，不再强制一定有框，
    # 否则测试会把这个刻意的设计当成缺陷。
    boxes = rec.get("boxes") or []
    check("检测框数量不超过上限 5", len(boxes) <= 5, f"len={len(boxes)}")
    geo_ok = all(
        0.0 <= float(b.get("x", -1)) <= 1.0
        and 0.0 <= float(b.get("y", -1)) <= 1.0
        and 0.0 < float(b.get("w", 0)) <= 1.0
        and 0.0 < float(b.get("h", 0)) <= 1.0
        and 0.0 < float(b.get("score", -1)) <= 1.0
        for b in boxes
    )
    check("检测框为合法的相对坐标与置信度", geo_ok, f"boxes={boxes}")
    check(
        "检测框置信度不超过整图置信度",
        all(float(b.get("score", 1)) <= float(rec.get("confidence", 100)) / 100 + 1e-6 for b in boxes),
        f"boxes={[b.get('score') for b in boxes]} vs 整图={rec.get('confidence')}",
    )
    if boxes:
        b0 = boxes[0]
        check(
            "最大框落在图像中部（不是贴边噪声）",
            0.02 <= float(b0["x"]) <= 0.9 and 0.02 <= float(b0["y"]) <= 0.9,
            f"最大框 x={b0['x']} y={b0['y']}",
        )

    # 多语言：同一条记录换语言取详情，应返回对应语言内容
    record_no = rec.get("record_no", "")
    if record_no:
        r_en = client.get(f"/api/history/{record_no}", params={"lang": "en-US"}, headers=auth_headers)
        en_name = (r_en.json() or {}).get("name", "") if r_en.status_code == 200 else ""
        check("记录支持英文取回", r_en.status_code == 200 and bool(en_name), r_en.text[:200])

        r_bo = client.get(f"/api/history/{record_no}", params={"lang": "bo-CN"}, headers=auth_headers)
        bo_name = (r_bo.json() or {}).get("name", "") if r_bo.status_code == 200 else ""
        check("藏语未翻译时回退中文（不返回空）", bool(bo_name), r_bo.text[:200])

    r = client.post(
        "/api/recognize",
        files={"file": ("leaf.jpg", make_leaf_image("healthy"), "image/jpeg")},
        data={"lang": "zh-CN", "channel": "qrcode"},
        headers=auth_headers,
    )
    check("扫码通道上传同样可用", r.status_code == 200, r.text[:200])

    r = client.post(
        "/api/recognize",
        files={"file": ("a.txt", b"this is not an image", "text/plain")},
        data={"lang": "zh-CN"},
        headers=auth_headers,
    )
    check("非图片文件被拒绝", r.status_code == 400, f"实际 {r.status_code}")

    print("\n=== 4. 农事问答（无密钥时降级本地知识库）===")
    r = client.post("/api/chat/ask", json={"question": "番茄叶子发黄是怎么回事", "lang": "zh-CN"}, headers=auth_headers)
    check("POST /api/chat/ask", r.status_code == 200, r.text[:300])
    chat = r.json() if r.status_code == 200 else {}
    check("返回了回答", len(chat.get("answer") or "") > 10, str(chat)[:200])
    check("标注了答案来源", chat.get("source") in {"local", "llm", "fallback"}, str(chat.get("source")))
    print(f"    答案来源：{chat.get('source')}，长度 {len(chat.get('answer') or '')} 字")

    r = client.get("/api/chat/quicks", params={"lang": "zh-CN"})
    check("GET /api/chat/quicks", r.status_code == 200 and len(r.json()) == 4, r.text[:200])
    r = client.get("/api/chat/quicks", params={"lang": "ug-CN"})
    quicks_ug = r.json() if r.status_code == 200 else []
    check("快捷提问支持维吾尔语", bool(quicks_ug) and bool(quicks_ug[0].get("text")), r.text[:200])

    print("\n=== 5. 历史记录 ===")
    r = client.get("/api/history", params={"page": 1, "page_size": 10, "lang": "zh-CN"}, headers=auth_headers)
    page = r.json() if r.status_code == 200 else {}
    check("GET /api/history", r.status_code == 200, r.text[:200])
    check("列表有数据", page.get("total", 0) > 0, str(page)[:200])
    check("列表项含缩略图 URL", all(x.get("image_url", "").startswith("/uploads/") for x in page.get("items", [])), str(page.get("items"))[:200])

    r = client.get("/api/history/chats", params={"page": 1, "page_size": 10}, headers=auth_headers)
    check("GET /api/history/chats", r.status_code == 200 and r.json().get("total", 0) > 0, r.text[:200])

    print("\n=== 6. 数据看板 ===")
    r = client.get("/api/stats/overview", params={"lang": "zh-CN"}, headers=auth_headers)
    ov = r.json() if r.status_code == 200 else {}
    check("GET /api/stats/overview", r.status_code == 200, r.text[:200])
    check("检测总量已累计", (ov.get("detection_total") or 0) >= 2, str(ov)[:200])
    check("平均置信度为数值", isinstance(ov.get("avg_confidence"), (int, float)), str(ov)[:200])

    r = client.get("/api/stats/trend", params={"days": 7}, headers=auth_headers)
    trend = r.json() if r.status_code == 200 else []
    check("GET /api/stats/trend", r.status_code == 200 and len(trend) == 7, f"len={len(trend)}")

    for path in ("disease-dist", "regions", "top-questions"):
        r = client.get(f"/api/stats/{path}", headers=auth_headers)
        check(f"GET /api/stats/{path}", r.status_code == 200, r.text[:200])

    print("\n=== 6.5 个人看板（只显示自己的数据）===")
    # 农户 A 前面做了 2 次识别（necrotic + healthy）和 1 次问答，个人看板必须只算这些
    r = client.get("/api/stats/mine", params={"lang": "zh-CN"}, headers=auth_headers)
    mine = r.json() if r.status_code == 200 else {}
    check("GET /api/stats/mine", r.status_code == 200, r.text[:200])
    check("农户累计检测为 2（自己 2 次识别）", mine.get("detection_total") == 2, str(mine)[:200])
    check("今日检测已计入", (mine.get("today_total") or 0) >= 1, str(mine)[:200])
    check("累计问答已计入", (mine.get("chat_total") or 0) >= 1, str(mine)[:200])
    check(
        "top_issues 是数组且不为空",
        isinstance(mine.get("top_issues"), list) and len(mine.get("top_issues")) > 0,
        str(mine)[:200],
    )
    check(
        "category_dist 是数组且不为空",
        isinstance(mine.get("category_dist"), list) and len(mine.get("category_dist")) > 0,
        str(mine)[:200],
    )
    check(
        "trend 为 7 天数组（补零后长度固定）",
        isinstance(mine.get("trend"), list) and len(mine.get("trend")) == 7,
        f"len={len(mine.get('trend') or [])}",
    )
    if mine.get("top_issues"):
        item = mine["top_issues"][0]
        check(
            "top_issues 条目含 code/name/count",
            all(k in item for k in ("code", "name", "count")),
            str(item)[:200],
        )
        check(
            "top_issues 的 name 按语言本地化（非空字符串）",
            isinstance(item.get("name"), str) and bool(item.get("name")),
            str(item)[:200],
        )

    # 用户 B 新注册：一条记录都没有，必须看不到 A 的数据
    r = client.post(
        "/api/auth/kiosk/register",
        json={"display_name": "个人看板乙", "phone": "13600000002", "lang": "zh-CN"},
    )
    user_b = r.json() if r.status_code == 200 else {}
    user_b_headers = {"Authorization": f"Bearer {user_b.get('access_token', '')}"}
    check("个人看板用户 B 注册成功", r.status_code == 200, r.text[:200])
    r = client.get("/api/stats/mine", headers=user_b_headers)
    mine_b = r.json() if r.status_code == 200 else {}
    check("用户 B 累计检测为 0（看不到 A 的数据）", mine_b.get("detection_total") == 0, str(mine_b)[:200])
    check(
        "空数据时 top_issues/category_dist 为空数组、trend 仍为 7 天",
        mine_b.get("top_issues") == []
        and mine_b.get("category_dist") == []
        and len(mine_b.get("trend") or []) == 7,
        str(mine_b)[:200],
    )

    # 游客没有可归属的记录，个人看板必须拒绝
    r = client.get("/api/stats/mine", headers=anon_headers)
    check("游客访问个人看板被拒（403）", r.status_code == 403, f"实际 {r.status_code}")

    print("\n=== 7. 管理后台 ===")
    r = client.get("/api/admin/dashboard", headers=admin_headers)
    check("GET /api/admin/dashboard", r.status_code == 200, r.text[:200])

    r = client.get("/api/admin/providers", headers=admin_headers)
    providers = r.json() if r.status_code == 200 else []
    check("GET /api/admin/providers（自动播种 6 家）", r.status_code == 200 and len(providers) == 6, f"len={len(providers)}")
    check("厂商接口不返回完整密钥", all("api_key" not in p for p in providers), "泄漏了 api_key 字段")

    r = client.post(
        "/api/admin/users",
        json={"username": "smoke_tester", "password": "test123456", "display_name": "冒烟测试账号", "role": "operator"},
        headers=admin_headers,
    )
    created = r.json() if r.status_code in (200, 201) else {}
    check("新增后台用户", r.status_code in (200, 201), r.text[:200])

    if created.get("id"):
        r = client.patch(f"/api/admin/users/{created['id']}", json={"display_name": "改名成功"}, headers=admin_headers)
        check("修改用户资料", r.status_code == 200 and r.json().get("display_name") == "改名成功", r.text[:200])

        r = client.delete(f"/api/admin/users/{created['id']}", headers=admin_headers)
        check("删除测试用户", r.status_code == 200, r.text[:200])

    r = client.put(
        "/api/admin/lang-resources",
        json={"lang": "bo-CN", "key": "card.detect.t", "value": "ནད་བརྟག"},
        headers=admin_headers,
    )
    check("新增多语言词条", r.status_code == 200, r.text[:200])

    r = client.get("/api/admin/logs", params={"page": 1, "page_size": 20}, headers=admin_headers)
    logs = r.json() if r.status_code == 200 else {}
    check("GET /api/admin/logs", r.status_code == 200, r.text[:200])
    check("写操作留痕", (logs.get("total") or 0) > 0, str(logs)[:200])

    print("\n=== 8. 游客模式策略（不留痕 + 后台锁定）===")
    before = client.get("/api/stats/overview", headers=admin_headers).json()

    r = client.post(
        "/api/recognize",
        files={"file": ("leaf.jpg", make_leaf_image("necrotic"), "image/jpeg")},
        data={"lang": "zh-CN", "channel": "local"},
        headers=anon_headers,
    )
    check("游客可以使用拍照识别", r.status_code == 200, r.text[:200])
    guest_rec = r.json() if r.status_code == 200 else {}
    check(
        "游客识别返回临时单号（T 开头，表示未入库）",
        str(guest_rec.get("record_no", "")).startswith("T"),
        f"record_no={guest_rec.get('record_no')}",
    )
    # 同上：不强制有框，只要求这个字段稳定是数组（有没有框取决于最终落在识别链的哪一级）
    check(
        "游客识别的检测框字段是数组",
        isinstance(guest_rec.get("boxes"), list),
        str(guest_rec.get("boxes"))[:200],
    )

    r = client.post(
        "/api/chat/ask",
        json={"question": "玉米什么时间追肥最好", "lang": "zh-CN"},
        headers=anon_headers,
    )
    check("游客可以使用农事问答", r.status_code == 200, r.text[:200])
    check("游客问答不返回记录 id", (r.json() or {}).get("record_id") is None, str(r.json())[:200])

    after = client.get("/api/stats/overview", headers=admin_headers).json()
    check(
        "游客操作不写入库（检测量不变）",
        after.get("detection_total") == before.get("detection_total"),
        f"{before.get('detection_total')} -> {after.get('detection_total')}",
    )
    check(
        "游客操作不写入库（问答量不变）",
        after.get("chat_total") == before.get("chat_total"),
        f"{before.get('chat_total')} -> {after.get('chat_total')}",
    )

    r = client.get("/api/history", headers=anon_headers)
    check("游客的历史记录为空", (r.json() or {}).get("total") == 0, r.text[:200])
    r = client.get("/api/history/chats", headers=anon_headers)
    check("游客的问答历史为空", (r.json() or {}).get("total") == 0, r.text[:200])

    if guest_rec.get("record_no"):
        r = client.get(f"/api/history/{guest_rec['record_no']}", headers=anon_headers)
        check("游客临时单号查不到详情（佐证确实没入库）", r.status_code == 404, f"实际 {r.status_code}")

    print("\n=== 9. 一体机注册 / 登录（手机号是账号主键）===")
    # 手机号格式非法：必须入口拦住，否则同一个人会拼出多个账号、记录跟着散掉
    r = client.post(
        "/api/auth/kiosk/register",
        json={"display_name": "张老汉", "phone": "123", "lang": "zh-CN"},
    )
    check("手机号格式非法被拒（400）", r.status_code == 400, f"实际 {r.status_code}")
    # 前端按响应体里的 code 取本地化文案（见 frontend/src/kiosk/api/index.js 的 errText），
    # 所以这个机器可读的 code 必须存在且稳定，不能只有中文 message
    check(
        "手机号格式非法返回 code=bad_phone",
        (r.json() or {}).get("code") == "bad_phone",
        r.text[:200],
    )

    r = client.post(
        "/api/auth/kiosk/register",
        json={"display_name": "张老汉", "phone": "13800001234", "lang": "zh-CN"},
    )
    kiosk = r.json() if r.status_code == 200 else {}
    check("手机号注册成功并返回 token", r.status_code == 200 and bool(kiosk.get("access_token")), r.text[:200])
    check(
        "注册出来的是农户角色（不是游客）",
        (kiosk.get("user") or {}).get("role") == "farmer",
        str(kiosk.get("user"))[:200],
    )
    kiosk_headers = {"Authorization": f"Bearer {kiosk.get('access_token', '')}"}

    # 同一手机号再注册必须被挡：否则同一人会裂成两个身份，历史记录分家
    r = client.post(
        "/api/auth/kiosk/register",
        json={"display_name": "张老汉", "phone": "13800001234", "lang": "zh-CN"},
    )
    check("重复注册同一手机号被拒（409）", r.status_code == 409, f"实际 {r.status_code}")

    # 没注册过的手机号不能直接登录
    r = client.post(
        "/api/auth/kiosk/login",
        json={"display_name": "李老汉", "phone": "13800009999", "lang": "zh-CN"},
    )
    check("未注册手机号登录被拒（404）", r.status_code == 404, f"实际 {r.status_code}")

    # 姓名和手机号不匹配必须拦住 —— 这是需求方强调的"一定要匹配"，
    # 否则张冠李戴会把别人的检测记录串到当前账号上
    r = client.post(
        "/api/auth/kiosk/login",
        json={"display_name": "王老汉", "phone": "13800001234", "lang": "zh-CN"},
    )
    check("姓名与手机号不匹配被拒（403）", r.status_code == 403, f"实际 {r.status_code}")

    # 姓名+手机号都对 → 正常登录，且认回的是注册时那个账号
    r = client.post(
        "/api/auth/kiosk/login",
        json={"display_name": "张老汉", "phone": "13800001234", "lang": "zh-CN"},
    )
    relogin = r.json() if r.status_code == 200 else {}
    check("姓名与手机号匹配可登录", r.status_code == 200 and bool(relogin.get("access_token")), r.text[:200])
    check(
        "登录认回注册时的同一个账号",
        (relogin.get("user") or {}).get("id") == (kiosk.get("user") or {}).get("id"),
        r.text[:200],
    )

    r = client.get("/api/admin/users", headers=kiosk_headers)
    check("农户仍然进不了后台（403）", r.status_code == 403, f"实际 {r.status_code}")

    before_k = client.get("/api/stats/overview", headers=admin_headers).json()
    r = client.post(
        "/api/recognize",
        files={"file": ("leaf.jpg", make_leaf_image("necrotic"), "image/jpeg")},
        data={"lang": "zh-CN", "channel": "local"},
        headers=kiosk_headers,
    )
    kiosk_rec = r.json() if r.status_code == 200 else {}
    check("农户可以用拍照识别", r.status_code == 200, r.text[:200])
    check(
        "农户识别返回正式单号（D 开头，已入库）",
        str(kiosk_rec.get("record_no", "")).startswith("D"),
        f"record_no={kiosk_rec.get('record_no')}",
    )
    r = client.get(f"/api/history/{kiosk_rec.get('record_no')}", headers=kiosk_headers)
    check("农户能查到自己刚生成的记录详情", r.status_code == 200, r.text[:200])
    after_k = client.get("/api/stats/overview", headers=admin_headers).json()
    check(
        "农户操作会入库（检测量 +1）",
        (after_k.get("detection_total") or 0) == (before_k.get("detection_total") or 0) + 1,
        f"{before_k.get('detection_total')} -> {after_k.get('detection_total')}",
    )
    r = client.get("/api/history", headers=kiosk_headers)
    check("农户的历史记录不为空", (r.json() or {}).get("total", 0) > 0, r.text[:200])

    # 另一个人用不同手机号注册后，彼此记录互不可见 —— 这正是"数据不会乱掉"的直接验证
    r = client.post(
        "/api/auth/kiosk/register",
        json={"display_name": "赵老汉", "phone": "13700005678", "lang": "zh-CN"},
    )
    other = r.json() if r.status_code == 200 else {}
    other_headers = {"Authorization": f"Bearer {other.get('access_token', '')}"}
    check("另一人用不同手机号也能注册", r.status_code == 200, r.text[:200])
    r = client.get("/api/history", headers=other_headers)
    check(
        "新账号看不到别人的记录（/api/history 为 0）",
        (r.json() or {}).get("total") == 0,
        r.text[:200],
    )

    print("\n" + "=" * 58)
    print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("\n失败明细：")
        for item in FAILED:
            print("  - " + item)
    print("=" * 58)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())


def test_smoke() -> None:
    """pytest 入口。"""
    assert main() == 0
